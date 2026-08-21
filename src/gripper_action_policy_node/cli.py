from __future__ import annotations

import argparse

from .runner import run_gripper_action_policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Gripper Forge Action policy node")
    parser.parse_args()
    return run_gripper_action_policy()


if __name__ == "__main__":
    raise SystemExit(main())
