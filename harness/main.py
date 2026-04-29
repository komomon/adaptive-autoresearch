#!/usr/bin/env python3
"""
Unified user-facing harness entrypoint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive Autoresearch unified entrypoint.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke = subparsers.add_parser("smoke", help="Run one smoke case through the target project.")
    smoke.add_argument("--manifest", required=True)
    smoke.add_argument("--case-file", required=True)
    smoke.add_argument("--output-dir", required=True)
    smoke.add_argument("--run-id", default="smoke-run")

    init_cmd = subparsers.add_parser("init", help="Initialize one run directory.")
    init_cmd.add_argument("--manifest", required=True)
    init_cmd.add_argument("--normalized-cases")

    eval_cmd = subparsers.add_parser("eval", help="Evaluate one existing candidate.")
    eval_cmd.add_argument("--manifest", required=True)
    eval_cmd.add_argument("--run-dir", required=True)
    eval_cmd.add_argument("--candidate-id", required=True)
    eval_cmd.add_argument("--strategy", choices=("staged", "full"))
    eval_cmd.add_argument("--limit-dev", type=int)
    eval_cmd.add_argument("--limit-holdout", type=int)
    eval_cmd.add_argument("--limit-cross-repo", type=int)
    eval_cmd.add_argument("--limit-canary", type=int)

    advance = subparsers.add_parser("advance", help="Advance exactly one new candidate.")
    advance.add_argument("--manifest", required=True)
    advance.add_argument("--run-dir", required=True)
    advance.add_argument("--candidate-id")
    advance.add_argument("--source", default="best")
    advance.add_argument("--split", default="dev")
    advance.add_argument("--strategy", choices=("staged", "full"))

    auto = subparsers.add_parser("auto", help="Run the full autoresearch loop.")
    auto.add_argument("--manifest", required=True)
    auto.add_argument("--run-dir")
    auto.add_argument("--rounds", type=int, default=3)
    auto.add_argument("--strategy", choices=("staged", "full"))

    return parser


def script_for(command: str) -> Path:
    mapping = {
        "smoke": "run_target_smoke.py",
        "init": "run_experiment.py",
        "eval": "run_candidate.py",
        "advance": "advance_candidate.py",
        "auto": "run_autoresearch.py",
    }
    return (Path(__file__).resolve().parent / mapping[command]).resolve()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command
    script_path = script_for(command)

    child_args: list[str] = [sys.executable, str(script_path)]
    for key, value in vars(args).items():
        if key == "command" or value is None:
            continue
        option = f"--{key.replace('_', '-')}"
        child_args.append(option)
        child_args.append(str(value))

    result = subprocess.run(child_args, cwd=str(Path.cwd()))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
