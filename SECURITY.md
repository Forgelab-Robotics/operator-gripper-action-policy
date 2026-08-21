# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting for this repository. Include affected versions,
reproduction steps, impact, and any suggested mitigation.

## Deployment boundary

The Gripper Action Policy Node is a command-line Dora Action node. It performs
no authentication and forwards validated gripper opening commands to a
downstream controller.

- Run policy nodes only on trusted hosts within an isolated robot network.
- This node is an Action provider: it commands a gripper. The caller supplies
  `opening_m`; mechanical bounds (`0..0.105 m`) are enforced by the Gateway
  schema and the downstream controller, not by this node.
- Shutdown cancels active goals, but cancel acceptance does not guarantee a
  controller terminal state; treat shutdown of an active goal as ambiguous and
  require an operator-accessible emergency stop near the robot.
- Do not expose policy processes or their configuration to untrusted networks.

Security fixes are supported on the latest released version.
