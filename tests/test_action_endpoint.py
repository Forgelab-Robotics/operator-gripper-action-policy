from __future__ import annotations

import asyncio

import pytest
from forge_msgs import GripperCommandFeedback, GripperCommandResult

from forge_tool import (
    ToolContext,
    ToolEndpointError,
    ToolEvent,
    ToolExecutionKey,
    ToolRequest,
)
from gripper_action_policy_node.action_endpoint import (
    DESCRIPTOR,
    GripperActionEndpoint,
    goal_id_for_key,
)


class Events:
    def __init__(self) -> None:
        self.items: list[ToolEvent] = []

    async def emit(self, event: ToolEvent) -> None:
        self.items.append(event)


def context(
    key: ToolExecutionKey,
    *,
    deadline_ms: int | None = None,
) -> ToolContext:
    return ToolContext(
        execution_key=key,
        tool_id="gripper.set_opening",
        implementation_id="gripper",
        endpoint_id="gripper.controller",
        operation="set_opening",
        deadline_ms=deadline_ms,
    )


def request(opening: object = 0.04, **extra: object) -> ToolRequest:
    return ToolRequest({"opening_m": opening, **extra})


def result(code: str = "SUCCESS") -> GripperCommandResult:
    return GripperCommandResult(
        error_code=code,
        message="done" if code == "SUCCESS" else code.lower(),
        elapsed_ns=123,
        position=0.04,
        velocity=0.01,
        effort=2.0,
        stalled=code == "STALLED",
        reached_goal=code == "SUCCESS",
    )


def test_descriptor_and_success_result_contract() -> None:
    operation = DESCRIPTOR.operations[0]
    assert DESCRIPTOR.endpoint_id == "gripper.controller"
    assert (
        operation.name,
        operation.semantics,
        operation.cancellable,
        operation.status_supported,
        operation.max_concurrency,
    ) == ("set_opening", "action", True, True, 1)

    sent = []
    endpoint = GripperActionEndpoint(
        lambda goal_id, goal: sent.append((goal_id, goal)),
        lambda goal_id: None,
    )
    key = ToolExecutionKey("invocation", "attempt")
    events = Events()
    accepted = asyncio.run(endpoint.start(request(), context(key), events))
    goal_id, goal = sent[0]

    assert accepted.details == {"goal_id": goal_id_for_key(key), "idempotent": False}
    assert goal_id == accepted.details["goal_id"]
    assert len(goal_id) <= 128
    assert goal.position == 0.04
    assert goal.max_velocity is None and goal.max_effort is None
    assert asyncio.run(endpoint.result(key)).status == "pending"

    asyncio.run(endpoint.handle_result(goal_id, result(), "succeeded"))
    response = asyncio.run(endpoint.result(key))
    assert response.status == "available"
    assert response.result is not None and response.result.status == "succeeded"
    assert response.result.outputs == {
        "goal_id": goal_id,
        "gripper_result": {
            "error_code": "SUCCESS",
            "message": "done",
            "elapsed_ns": 123,
            "position": 0.04,
            "velocity": 0.01,
            "effort": 2.0,
            "stalled": False,
            "reached_goal": True,
        },
    }
    assert asyncio.run(endpoint.status(key)).phase == "completed"


@pytest.mark.parametrize(
    "bad_request",
    [
        ToolRequest({}),
        request(0.04, max_velocity=1.0),
        request(True),
        request("0.04"),
    ],
)
def test_invalid_input_is_rejected_without_sending(bad_request: ToolRequest) -> None:
    sent = []
    endpoint = GripperActionEndpoint(
        lambda *args: sent.append(args),
        lambda *args: None,
    )
    with pytest.raises(ToolEndpointError) as captured:
        asyncio.run(
            endpoint.start(
                bad_request,
                context(ToolExecutionKey("invalid", "attempt")),
                Events(),
            )
        )
    assert captured.value.error.code == "GRIPPER_INVALID_GOAL"
    assert sent == []


def test_endpoint_itself_rejects_non_finite_opening() -> None:
    sent = []
    endpoint = GripperActionEndpoint(
        lambda *args: sent.append(args),
        lambda *args: None,
    )
    malformed = request()
    object.__setattr__(malformed, "arguments", {"opening_m": float("inf")})

    with pytest.raises(ToolEndpointError) as captured:
        asyncio.run(
            endpoint.start(
                malformed,
                context(ToolExecutionKey("non-finite", "attempt")),
                Events(),
            )
        )
    assert captured.value.error.code == "GRIPPER_INVALID_GOAL"
    assert sent == []


def test_duplicate_busy_and_conflicting_attempts() -> None:
    sent = []
    endpoint = GripperActionEndpoint(
        lambda *args: sent.append(args),
        lambda *args: None,
    )
    key = ToolExecutionKey("one", "attempt")
    first = asyncio.run(endpoint.start(request(), context(key), Events()))
    duplicate = asyncio.run(endpoint.start(request(), context(key), Events()))
    assert duplicate.details == {"goal_id": first.details["goal_id"], "idempotent": True}
    assert len(sent) == 1

    with pytest.raises(ToolEndpointError) as busy:
        asyncio.run(
            endpoint.start(
                request(),
                context(ToolExecutionKey("two", "attempt")),
                Events(),
            )
        )
    assert busy.value.error.code == "BUSY"
    assert busy.value.error.retryable is True

    with pytest.raises(ToolEndpointError) as conflict:
        asyncio.run(endpoint.start(request(0.05), context(key), Events()))
    assert conflict.value.error.code == "FORGE_EXECUTION_CONFLICT"


def test_feedback_cancel_and_original_terminal_error_code() -> None:
    cancels = []
    endpoint = GripperActionEndpoint(
        lambda *args: None,
        lambda goal_id: cancels.append(goal_id),
    )
    key = ToolExecutionKey("one", "attempt")
    events = Events()
    accepted = asyncio.run(endpoint.start(request(), context(key), events))
    goal_id = accepted.details["goal_id"]
    feedback = GripperCommandFeedback(
        elapsed_ns=50,
        position=0.02,
        velocity=0.1,
        effort=1.5,
        stalled=False,
        reached_goal=False,
    )
    asyncio.run(endpoint.handle_feedback(goal_id, feedback))
    cancel = asyncio.run(endpoint.cancel(key, "operator"))
    asyncio.run(endpoint.cancel(key, "duplicate"))
    asyncio.run(endpoint.handle_result(goal_id, result("CANCELED"), "canceled"))

    assert events.items[0].type == "progress"
    assert events.items[0].data["position"] == 0.02
    assert cancel.status == "accepted"
    assert cancels == [goal_id]
    assert asyncio.run(endpoint.status(key)).phase == "cancelled"
    terminal = asyncio.run(endpoint.result(key)).result
    assert terminal is not None
    assert terminal.outputs["gripper_result"]["error_code"] == "CANCELED"

    failed = GripperActionEndpoint(lambda *args: None, lambda *args: None)
    failed_key = ToolExecutionKey("failed", "attempt")
    failed_id = asyncio.run(
        failed.start(request(), context(failed_key), Events())
    ).details["goal_id"]
    asyncio.run(failed.handle_result(failed_id, result("HARDWARE_FAULT"), "aborted"))
    failed_result = asyncio.run(failed.result(failed_key)).result
    assert failed_result is not None and failed_result.error is not None
    assert failed_result.error.code == "HARDWARE_FAULT"


def test_result_absent_deadline_and_shutdown_ambiguity() -> None:
    cancels = []
    endpoint = GripperActionEndpoint(
        lambda *args: None,
        lambda goal_id: cancels.append(goal_id),
        epoch_ms=lambda: 1_000,
    )
    absent_key = ToolExecutionKey("absent", "attempt")
    assert asyncio.run(endpoint.result(absent_key)).status == "not_found"
    assert asyncio.run(endpoint.status(absent_key)).phase == "unknown"

    with pytest.raises(ToolEndpointError) as expired:
        asyncio.run(
            endpoint.start(
                request(),
                context(ToolExecutionKey("expired", "attempt"), deadline_ms=1_000),
                Events(),
            )
        )
    assert expired.value.error.code == "FORGE_DEADLINE_EXCEEDED"

    key = ToolExecutionKey("active", "attempt")
    accepted = asyncio.run(endpoint.start(request(), context(key), Events()))
    outcome = endpoint.begin_shutdown()
    assert outcome.active_goal_id == accepted.details["goal_id"]
    assert outcome.cancel_requested is True
    assert outcome.terminal_confirmed is False
    assert cancels == [accepted.details["goal_id"]]
    assert asyncio.run(endpoint.status(key)).phase == "stopping"

    with pytest.raises(ToolEndpointError) as stopping:
        asyncio.run(
            endpoint.start(
                request(),
                context(ToolExecutionKey("new", "attempt")),
                Events(),
            )
        )
    assert stopping.value.error.code == "FORGE_ENDPOINT_STOPPING"
