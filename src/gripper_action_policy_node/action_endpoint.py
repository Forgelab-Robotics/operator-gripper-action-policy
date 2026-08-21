"""Forge Action endpoint for the GripperCommand controller."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from forge_msgs import GripperCommandFeedback, GripperCommandGoal, GripperCommandResult

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEndpointDescriptor,
    ToolEndpointError,
    ToolError,
    ToolEvent,
    ToolEventEmitter,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolOperationDescriptor,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
)

ENDPOINT_ID = "gripper.controller"
OPERATION = "set_opening"
DESCRIPTOR = ToolEndpointDescriptor(
    protocol_version=TOOL_ENDPOINT_PROTOCOL,
    endpoint_id=ENDPOINT_ID,
    operations=(
        ToolOperationDescriptor(
            name=OPERATION,
            semantics="action",
            cancellable=True,
            status_supported=True,
            max_concurrency=1,
        ),
    ),
)

GoalSender = Callable[[str, GripperCommandGoal], None]
CancelSender = Callable[[str], None]
logger = logging.getLogger(__name__)


def goal_id_for_key(key: ToolExecutionKey) -> str:
    """Map an execution attempt to a deterministic, bounded controller goal ID."""
    digest = hashlib.sha256(
        f"{key.invocation_id}\0{key.attempt_id}".encode()
    ).hexdigest()
    return f"tool-{digest}"


def _endpoint_error(code: str, message: str, *, retryable: bool = False) -> ToolEndpointError:
    return ToolEndpointError(ToolError(code=code, message=message, retryable=retryable))


def _goal(arguments: Mapping[str, Any]) -> GripperCommandGoal:
    if set(arguments) != {"opening_m"}:
        missing = sorted({"opening_m"} - set(arguments))
        unexpected = sorted(set(arguments) - {"opening_m"})
        raise _endpoint_error(
            "GRIPPER_INVALID_GOAL",
            f"invalid arguments: missing={missing}, unexpected={unexpected}",
        )
    value = arguments["opening_m"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _endpoint_error("GRIPPER_INVALID_GOAL", "opening_m must be a number")
    opening = float(value)
    if not math.isfinite(opening):
        raise _endpoint_error("GRIPPER_INVALID_GOAL", "opening_m must be finite")
    return GripperCommandGoal(position=opening, max_velocity=None, max_effort=None)


@dataclass(slots=True)
class _Execution:
    key: ToolExecutionKey
    goal_id: str
    arguments_json: str
    emitter: ToolEventEmitter
    phase: str = "accepted"
    result: ToolResult | None = None


@dataclass(frozen=True, slots=True)
class ShutdownOutcome:
    active_goal_id: str | None
    cancel_requested: bool
    terminal_confirmed: bool


class GripperActionEndpoint:
    """Action SPI adapter over injected gripper goal and cancel senders."""

    def __init__(
        self,
        send_goal: GoalSender,
        send_cancel: CancelSender,
        *,
        result_cache_size: int = 128,
        epoch_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        if result_cache_size < 1:
            raise ValueError("result_cache_size must be positive")
        self._send_goal = send_goal
        self._send_cancel = send_cancel
        self._result_cache_size = result_cache_size
        self._epoch_ms = epoch_ms
        self._executions: OrderedDict[ToolExecutionKey, _Execution] = OrderedDict()
        self._by_goal_id: dict[str, ToolExecutionKey] = {}
        self._active: ToolExecutionKey | None = None
        self._accepting = True

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        if context.operation != OPERATION:
            raise _endpoint_error(
                "FORGE_PROTOCOL_UNKNOWN_OPERATION",
                f"unknown operation {context.operation!r}",
            )
        if not self._accepting:
            raise _endpoint_error(
                "FORGE_ENDPOINT_STOPPING",
                "gripper Action endpoint is shutting down and no longer accepts goals",
                retryable=True,
            )
        if context.deadline_ms is not None and self._epoch_ms() >= context.deadline_ms:
            raise _endpoint_error(
                "FORGE_DEADLINE_EXCEEDED",
                "the Tool invocation deadline has expired",
            )

        key = context.execution_key
        arguments_json = json.dumps(request.arguments, sort_keys=True, separators=(",", ":"))
        existing = self._executions.get(key)
        if existing is not None:
            if existing.arguments_json != arguments_json:
                raise _endpoint_error(
                    "FORGE_EXECUTION_CONFLICT",
                    "execution key was already used with different action arguments",
                )
            return ToolAccepted(details={"goal_id": existing.goal_id, "idempotent": True})
        if self._active is not None:
            raise _endpoint_error(
                "BUSY",
                "gripper controller already has an active goal",
                retryable=True,
            )

        try:
            goal = _goal(request.arguments)
        except ToolEndpointError:
            raise
        except (TypeError, ValueError) as exc:
            raise _endpoint_error("GRIPPER_INVALID_GOAL", str(exc)) from exc

        goal_id = goal_id_for_key(key)
        execution = _Execution(key, goal_id, arguments_json, events)
        self._executions[key] = execution
        self._by_goal_id[goal_id] = key
        self._active = key
        try:
            self._send_goal(goal_id, goal)
        except Exception:
            self._executions.pop(key, None)
            self._by_goal_id.pop(goal_id, None)
            self._active = None
            raise
        execution.phase = "running"
        return ToolAccepted(details={"goal_id": goal_id, "idempotent": False})

    async def cancel(
        self, key: ToolExecutionKey, reason: str | None = None
    ) -> ToolControlResponse:
        execution = self._executions.get(key)
        if execution is None:
            return ToolControlResponse(
                command="cancel",
                status="rejected",
                error=ToolError(
                    code="FORGE_EXECUTION_NOT_FOUND",
                    message="execution key is unknown",
                ),
            )
        if execution.result is not None:
            return ToolControlResponse(command="cancel", status="terminal")
        if execution.phase != "stopping":
            self._send_cancel(execution.goal_id)
            execution.phase = "stopping"
        return ToolControlResponse(
            command="cancel",
            status="accepted",
            details={"goal_id": execution.goal_id, "reason": reason},
        )

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        execution = self._executions.get(key)
        if execution is None:
            return ToolExecutionStatus(
                phase="unknown",
                error=ToolError(
                    code="FORGE_EXECUTION_NOT_FOUND",
                    message="execution key is unknown or its result expired",
                ),
            )
        return ToolExecutionStatus(
            phase=execution.phase,  # type: ignore[arg-type]
            error=(
                execution.result.error
                if execution.phase in ("failed", "unknown") and execution.result is not None
                else None
            ),
            details={"goal_id": execution.goal_id, "operation": OPERATION},
        )

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        execution = self._executions.get(key)
        if execution is None:
            return ToolResultResponse(status="not_found")
        if execution.result is None:
            return ToolResultResponse(status="pending")
        return ToolResultResponse(status="available", result=execution.result)

    async def handle_feedback(self, goal_id: str, feedback: GripperCommandFeedback) -> None:
        execution = self._execution_for_goal(goal_id)
        if execution is None or execution.result is not None:
            return
        try:
            await execution.emitter.emit(
                ToolEvent(
                    type="progress",
                    data={"goal_id": goal_id, **feedback.model_dump(mode="json")},
                )
            )
        except Exception:
            logger.exception("failed to emit advisory gripper progress event")

    async def handle_result(
        self,
        goal_id: str,
        result: GripperCommandResult,
        goal_status: str,
    ) -> None:
        execution = self._execution_for_goal(goal_id)
        if execution is None or execution.result is not None:
            return
        outputs = {
            "goal_id": goal_id,
            "gripper_result": result.model_dump(mode="json"),
        }
        code = result.error_code
        if goal_status == "succeeded" and code == "SUCCESS":
            execution.phase = "completed"
            execution.result = ToolResult(status="succeeded", outputs=outputs)
            event_type = "executor_completed"
        elif goal_status == "canceled" or code == "CANCELED":
            execution.phase = "cancelled"
            execution.result = ToolResult(status="cancelled", outputs=outputs)
            event_type = "cancelled"
        else:
            error = ToolError(code=code, message=result.message, retryable=code == "BUSY")
            execution.phase = "failed"
            execution.result = ToolResult(status="failed", outputs=outputs, error=error)
            event_type = "executor_failed"
        if self._active == execution.key:
            self._active = None
        try:
            await execution.emitter.emit(
                ToolEvent(type=event_type, data={"goal_id": goal_id, "error_code": code})
            )
        except Exception:
            logger.exception("failed to emit advisory gripper terminal event")
        self._executions.move_to_end(execution.key)
        self._trim_cache()

    def begin_shutdown(self) -> ShutdownOutcome:
        """Stop admission and request cancellation without claiming completion."""
        self._accepting = False
        if self._active is None:
            return ShutdownOutcome(None, False, True)
        execution = self._executions[self._active]
        if execution.result is not None:
            return ShutdownOutcome(execution.goal_id, False, True)
        if execution.phase == "stopping":
            return ShutdownOutcome(execution.goal_id, True, False)
        try:
            self._send_cancel(execution.goal_id)
        except Exception:
            logger.exception("failed to request cancellation during endpoint shutdown")
            return ShutdownOutcome(execution.goal_id, False, False)
        execution.phase = "stopping"
        return ShutdownOutcome(execution.goal_id, True, False)

    def _execution_for_goal(self, goal_id: str) -> _Execution | None:
        key = self._by_goal_id.get(goal_id)
        return None if key is None else self._executions.get(key)

    def _trim_cache(self) -> None:
        terminal = sum(item.result is not None for item in self._executions.values())
        while terminal > self._result_cache_size:
            key, execution = next(
                (key, item) for key, item in self._executions.items() if item.result is not None
            )
            self._executions.pop(key)
            self._by_goal_id.pop(execution.goal_id, None)
            terminal -= 1


__all__ = [
    "DESCRIPTOR",
    "ENDPOINT_ID",
    "GripperActionEndpoint",
    "OPERATION",
    "ShutdownOutcome",
    "goal_id_for_key",
]
