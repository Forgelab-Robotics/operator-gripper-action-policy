# Gripper Action Policy Node

独立 Dora policy node，为 Forge Action endpoint
`gripper.controller/set_opening` 提供 `forge_msgs.GripperCommand` 控制器适配。

## Node、Endpoint 与 Tool API / Capability summary

| 项目 | 当前实现 |
| --- | --- |
| 生产 Node | 1：`gripper_action_policy`；源码命令 `gripper-action-policy`，打包入口 `dist/gripper_action_policy` |
| Tool 接入方式 | Dora `ToolMessage` provider；通过 Gateway 暴露调用入口 |
| 直接 HTTP Tool API | 0；本 Node 不监听 HTTP，调用地址属于 Gateway |
| Endpoint 数 | 1：`gripper.controller` |
| operation 数 | 1：`set_opening`（Action，可取消、可查状态，最大并发 1） |
| Gateway Tool 数 | 由部署的 `tools.specs` 决定；`robot-control-sim` 为此 operation 配置 1 个 Tool：`sim.set_gripper_opening` |

| Tool ID（Skill 配置） | Endpoint / operation | provider Node |
| --- | --- | --- |
| `sim.set_gripper_opening` | `gripper.controller / set_opening` | `gripper_action_policy` |

调用参数严格为 `{"opening_m": 0.04}`（单位 m）；完整行为见下方[契约](#契约)。
本节点把 Tool 调用转换为 `GripperCommandGoal`，再将下游 feedback/result 转回 Tool 状态与结果。
它不承担控制器执行，也不运行学习模型。

```text
Gateway -> gripper_action_policy -> gripper_action_controller -> MuJoCo / robot Adapter
                                   <- JointState feedback <-
```

[`gripper_action_controller`](https://github.com/PhyAgentOS/operator-controls/tree/dev/packages/gripper_action_controller)
属于 `operator-controls`，按目标生成关节位置命令并监视到位、卡滞、超时和取消；它自身不提供 ToolEndpoint。
本 policy 的米制 opening 接口不能直接当作弧度制夹爪接口使用。
实现：[descriptor 与 Action 适配](src/gripper_action_policy_node/action_endpoint.py)、
[Dora runner](src/gripper_action_policy_node/runner.py)。

兼容性：当前依赖声明为 `dora-rs==0.4.1`、`forge-msgs==1.0.1`；以 [pyproject.toml](pyproject.toml) 与 [uv.lock](uv.lock) 为准。 Tool 协议实现为仓库内 vendored 代码。 这些声明不构成跨版本互操作保证；使用制品时还需核对 build revision 和 Skill lock。

后续修改 Node 入口、Endpoint 或 Tool API 时，请同步更新本节及对应配置/契约，遵循 [Node README 规范](https://github.com/PhyAgentOS/forge/blob/master/CONTRIBUTING.md#node-readme-contract)。

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
