#!/usr/bin/env python3
"""
Top-level autoresearch loop:
- initialize run if needed
- establish baseline if needed
- advance candidates for multiple rounds
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from version_backend import read_json, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full autoresearch loop.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", help="Optional existing run directory. If omitted, a new run is initialized.")
    parser.add_argument("--rounds", type=int, default=3, help="Maximum auto-optimization rounds to run.")
    parser.add_argument("--strategy", choices=("staged", "full"), help="Optional candidate evaluation strategy override.")
    return parser.parse_args()


def run_json_command(command: list[str], cwd: Path) -> Dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\ncommand={' '.join(command)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"stdout": result.stdout}


def initialize_run(manifest_path: Path, cwd: Path) -> Path:
    result = subprocess.run(
        [
            sys.executable,
            str((Path(__file__).resolve().parent / "run_experiment.py").resolve()),
            "--manifest",
            str(manifest_path),
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"run_experiment failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    for line in result.stdout.splitlines():
        if line.startswith("Run dir: "):
            return Path(line.split("Run dir: ", 1)[1].strip()).resolve()
    raise RuntimeError(f"Could not parse run directory from run_experiment output:\n{result.stdout}")


def ensure_baseline(manifest_path: Path, run_dir: Path, strategy: str | None, cwd: Path) -> Dict[str, Any]:
    decision_path = run_dir / "decisions" / "baseline.decision.json"
    if decision_path.exists():
        return read_json(decision_path)
    command = [
        sys.executable,
        str((Path(__file__).resolve().parent / "run_candidate.py").resolve()),
        "--manifest",
        str(manifest_path),
        "--run-dir",
        str(run_dir),
        "--candidate-id",
        "baseline",
    ]
    if strategy:
        command.extend(["--strategy", strategy])
    run_json_command(command, cwd)
    return read_json(decision_path)


def update_supervisor(run_dir: Path, **fields: object) -> None:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state.setdefault("supervisor", {})
    run_state["supervisor"].update(fields)
    write_json(run_state_path, run_state)


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    cwd = Path.cwd()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else initialize_run(manifest_path, cwd)

    baseline_decision = ensure_baseline(manifest_path, run_dir, args.strategy, cwd)
    last_payload: Dict[str, Any] = {"baseline": baseline_decision}

    for index in range(1, args.rounds + 1):
        update_supervisor(
            run_dir,
            status="advancing_candidate",
            next_action=f"auto round {index}",
            auto_round=index,
        )
        command = [
            sys.executable,
            str((Path(__file__).resolve().parent / "advance_candidate.py").resolve()),
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
        ]
        if args.strategy:
            command.extend(["--strategy", args.strategy])
        payload = run_json_command(command, cwd)
        last_payload = payload
        candidate_decision = payload.get("candidate", {}).get("decision")
        if candidate_decision == "keep":
            continue

    update_supervisor(
        run_dir,
        status="auto_loop_completed",
        next_action="inspect best candidate and lessons",
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "rounds": args.rounds,
                "last_result": last_payload,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
