# Gripper Action Policy Node

[English](README.md) | [简体中文](README_zh.md)

Standalone Dora policy Node that adapts the Forge Action Endpoint
`gripper.controller/set_opening` to a `forge_msgs.GripperCommand` controller.

## Node, Endpoint and Tool API

| Item | Current implementation |
| --- | --- |
| Production Nodes | 1: `gripper_action_policy`; source command `gripper-action-policy`, packaged entrypoint `dist/gripper_action_policy` |
| Tool integration | Dora `ToolMessage` provider; caller-facing access through Gateway |
| Direct HTTP Tool API | 0; this Node does not listen on HTTP; Gateway owns the invocation URL |
| Endpoints | 1: `gripper.controller` |
| Operations | 1: `set_opening` (Action, cancellable, status supported, maximum concurrency 1) |
| Gateway Tools | Deployment-defined in `tools.specs`; `robot-control-sim` binds 1 Tool to this operation: `sim.set_gripper_opening` |

| Tool ID (Skill configuration) | Endpoint / operation | Provider Node |
| --- | --- | --- |
| `sim.set_gripper_opening` | `gripper.controller / set_opening` | `gripper_action_policy` |

Arguments are exactly `{"opening_m": 0.04}` (metres); see the [contract](#contract) below.
This Node translates Tool invocations to `GripperCommandGoal`, then translates downstream
feedback/results into Tool status and results. It neither executes the controller nor runs a learned model.

```text
Gateway -> gripper_action_policy -> gripper_action_controller -> MuJoCo / robot Adapter
                                   <- JointState feedback <-
```

[`gripper_action_controller`](https://github.com/PhyAgentOS/operator-controls/tree/dev/packages/gripper_action_controller)
belongs to `operator-controls`. It generates joint-position commands and monitors arrival, stall,
timeout and cancellation; it does not provide a ToolEndpoint itself.
This policy's metre-based opening interface cannot directly serve a radian-based gripper.
Implementation: [descriptor and Action adapter](src/gripper_action_policy_node/action_endpoint.py),
[Dora runner](src/gripper_action_policy_node/runner.py).

Compatibility: current dependency declarations are `dora-rs==0.4.1`, `forge-msgs==1.0.1`. See [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock). The Tool protocol implementation is vendored in this repository. These declarations do not guarantee cross-version interoperability; also check the build revision and Skill lock when using artifacts.

Changes to Node entrypoints, Endpoints or Tool APIs must update this section and the associated configuration/contracts. Follow the [Node README contract](https://github.com/PhyAgentOS/forge/blob/master/CONTRIBUTING.md#node-readme-contract).

## Contract

- The descriptor exposes `set_opening` as a cancellable Action with status lookup and maximum concurrency 1.
- Caller arguments are exactly `{"opening_m": <finite number>}`.
- The policy validates finiteness and converts the value to
  `GripperCommandGoal(position=opening_m, max_velocity=None, max_effort=None)`.
- Gateway schema and the downstream controller each validate the `0..0.105 m` mechanical bounds. This Node does not duplicate those bounds.
- Each Tool attempt maps to a deterministic, bounded controller `goal_id`; retrying the same attempt does not resend the goal.

## Install and run

Forge messages resolve from public package indexes (`forge-msgs==1.0.1`);
the Forge Tool protocol is vendored under `src/forge_tool`:

```bash
uv sync
uv run gripper-action-policy
```

## Dora ports

Inputs:

- `tick`: drives Endpoint lease registration and renewal.
- `tool_in`: Forge `ToolMessage`, including registry responses and Action control requests.
- `gripper_feedback`: `forge_msgs.GripperCommandFeedback`, with `goal_id` in metadata.
- `gripper_result`: `forge_msgs.GripperCommandResult`, with `goal_id` and `goal_status` in metadata.

Outputs:

- `tool_out`: registration, unregistration, Action responses, status, results and `ToolEvent`.
- `gripper_goal`: `forge_msgs.GripperCommandGoal`, with `goal_id` in metadata.
- `gripper_cancel`: boolean trigger, with `goal_id` in metadata.

The runner composes Forge's public `ToolEndpointHandler`, `DoraToolEndpointBinding` and
`EndpointLease`; it does not implement its own Tool Wire dispatch. Shutdown first stops
accepting new goals and requests cancellation. Accepted cancellation is not a controller-confirmed
terminal state, so shutdown with an active goal is explicitly treated as ambiguous.

## Test and build

```bash
uv run pytest
uv run ruff check .
./scripts/build_pyinstaller.sh
```

The PyInstaller single-file output is `dist/gripper_action_policy`.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
