from __future__ import annotations

from forge_msgs import GripperCommandFeedback, GripperCommandGoal, GripperCommandResult

from forge_tool import (
    ToolContext,
    ToolExecutionKey,
    ToolRequest,
    invoke_response_from_payload,
    make_invoke_request_envelope,
)
from forge_tool._tool_message import ToolMessage
from forge_tool.dora import tool_envelope_to_message, tool_message_to_envelope
from gripper_action_policy_node.runner import GripperActionPolicyRunner


class Node:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object, dict]] = []

    def send_output(self, output_id: str, value: object, **kwargs: object) -> None:
        self.sent.append((output_id, value, kwargs))


def envelope(value: object):
    return tool_message_to_envelope(ToolMessage.from_arrow(value))


def test_runner_drives_all_declared_ports_and_shutdown_order() -> None:
    node = Node()
    runner = GripperActionPolicyRunner(
        node,
        endpoint_instance_id="instance-1",
        clock=lambda: 10.0,
    )

    runner.process_event({"type": "INPUT", "id": "tick", "value": None})
    assert node.sent[0][0] == "tool_out"
    assert envelope(node.sent[0][1]).message_type == "endpoint.register"

    context = ToolContext(
        execution_key=ToolExecutionKey("invocation", "attempt"),
        tool_id="gripper.set_opening",
        implementation_id="gripper",
        endpoint_id="gripper.controller",
        operation="set_opening",
    )
    invoke = make_invoke_request_envelope(
        ToolRequest({"opening_m": 0.05}),
        context,
        request_id="invoke-1",
        endpoint_instance_id="instance-1",
    )
    runner.process_event(
        {
            "type": "INPUT",
            "id": "tool_in",
            "value": tool_envelope_to_message(invoke).to_arrow(),
        }
    )

    goal_call = next(call for call in node.sent if call[0] == "gripper_goal")
    goal = GripperCommandGoal.from_arrow(goal_call[1])
    goal_id = goal_call[2]["metadata"]["goal_id"]
    assert goal.position == 0.05
    assert goal.max_velocity is None and goal.max_effort is None
    accepted_call = next(
        call
        for call in node.sent
        if call[0] == "tool_out" and envelope(call[1]).message_type == "tool.invoke.response"
    )
    accepted = invoke_response_from_payload(envelope(accepted_call[1]).payload)
    assert accepted.details["goal_id"] == goal_id

    feedback = GripperCommandFeedback(
        elapsed_ns=10,
        position=0.03,
        velocity=None,
        effort=None,
        stalled=False,
        reached_goal=False,
    )
    runner.process_event(
        {
            "type": "INPUT",
            "id": "gripper_feedback",
            "value": feedback.to_arrow(),
            "metadata": {"parameters": {"goal_id": goal_id}},
        }
    )
    assert any(
        call[0] == "tool_out" and envelope(call[1]).message_type == "tool.event"
        for call in node.sent
    )

    result = GripperCommandResult(
        error_code="SUCCESS",
        message="done",
        elapsed_ns=20,
        position=0.05,
        velocity=0.0,
        effort=1.0,
        stalled=False,
        reached_goal=True,
    )
    runner.process_event(
        {
            "type": "INPUT",
            "id": "gripper_result",
            "value": result.to_arrow(),
            "metadata": {
                "parameters": {"goal_id": goal_id, "goal_status": "succeeded"}
            },
        }
    )
    assert runner.process_event({"type": "STOP"}) == 0
    assert envelope(node.sent[-1][1]).message_type == "endpoint.unregister"


def test_runner_stop_cancels_active_goal_before_unregister() -> None:
    node = Node()
    runner = GripperActionPolicyRunner(node, endpoint_instance_id="instance-1")
    context = ToolContext(
        execution_key=ToolExecutionKey("active", "attempt"),
        tool_id="gripper.set_opening",
        implementation_id="gripper",
        endpoint_id="gripper.controller",
        operation="set_opening",
    )
    invoke = make_invoke_request_envelope(
        ToolRequest({"opening_m": 0.04}),
        context,
        request_id="invoke-1",
        endpoint_instance_id="instance-1",
    )
    runner.process_event(
        {
            "type": "INPUT",
            "id": "tool_in",
            "value": tool_envelope_to_message(invoke).to_arrow(),
        }
    )

    assert runner.process_event({"type": "STOP"}) == 0
    output_ids = [call[0] for call in node.sent]
    assert output_ids.index("gripper_cancel") < len(output_ids) - 1
    assert envelope(node.sent[-1][1]).message_type == "endpoint.unregister"
