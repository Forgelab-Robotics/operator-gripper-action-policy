# Gripper Action Policy Node

独立 Dora policy node，为 Forge Action endpoint
`gripper.controller/set_opening` 提供 `forge_msgs.GripperCommand` 控制器适配。

## 契约

- endpoint descriptor：`set_opening` 是可取消、支持状态查询、最大并发为 1 的 Action。
- caller 参数严格为 `{"opening_m": <finite number>}`。
- policy node 只校验有限数并转换为
  `GripperCommandGoal(position=opening_m, max_velocity=None, max_effort=None)`。
- `0..0.105 m` 的机械边界由 Gateway schema 与下游 controller 分别验证。本节点不复制该边界。
- Tool attempt 映射到确定且有界的 controller `goal_id`；同一 attempt 重试不会重复下发。

## 安装与运行

Forge 消息从公共包索引解析（`forge-msgs==1.0.1`）；Forge Tool 协议以 `src/forge_tool` 内置（vendored）：

```bash
uv sync
uv run gripper-action-policy
```

## Dora 端口

输入：

- `tick`：驱动 endpoint lease 注册和续租。
- `tool_in`：Forge `ToolMessage`，包括 registry response 与 Action 控制请求。
- `gripper_feedback`：`forge_msgs.GripperCommandFeedback`，metadata 带 `goal_id`。
- `gripper_result`：`forge_msgs.GripperCommandResult`，metadata 带 `goal_id` 和
  `goal_status`。

输出：

- `tool_out`：注册、注销、Action 响应、状态、结果及 `ToolEvent`。
- `gripper_goal`：`forge_msgs.GripperCommandGoal`，metadata 带 `goal_id`。
- `gripper_cancel`：布尔触发值，metadata 带 `goal_id`。

runner 组合 Forge 公共 `ToolEndpointHandler`、`DoraToolEndpointBinding` 与
`EndpointLease`，不自行实现 Tool Wire dispatch。进程停止时先停止接收新 goal 并请求取消；
cancel 被接收不代表 controller 已确认终态，因此活跃 goal 的 shutdown 状态明确视为 ambiguous。

## 测试与构建

```bash
uv run pytest
uv run ruff check .
./scripts/build_pyinstaller.sh
```

PyInstaller 单文件产物为 `dist/gripper_action_policy`。

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
