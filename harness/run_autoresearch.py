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
import sys
from pathlib import Path
from typing import Any, Dict

from _shared import (
    count_completed_rounds,
    load_manifest,
    read_json,
    run_json_command,
    run_subprocess,
    update_supervisor,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full autoresearch loop.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", help="Optional existing run directory. If omitted, a new run is initialized.")
    parser.add_argument("--rounds", type=int, default=3, help="Maximum auto-optimization rounds to run.")
    parser.add_argument("--round-retries", type=int, help="Optional retry count for each auto round.")
    parser.add_argument("--strategy", choices=("staged", "full"), help="Optional candidate evaluation strategy override.")
    return parser.parse_args()


def initialize_run(manifest_path: Path, cwd: Path) -> Path:
    result = run_subprocess(
        [
            sys.executable,
            str((Path(__file__).resolve().parent / "run_experiment.py").resolve()),
            "--manifest",
            str(manifest_path),
        ],
        cwd,
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


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    cwd = Path.cwd()
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        sys.stderr.write(f"[auto] Using existing run dir: {run_dir}\n")
    else:
        sys.stderr.write("[auto] Initializing new run\n")
        run_dir = initialize_run(manifest_path, cwd)
        sys.stderr.write(f"[auto] Run dir: {run_dir}\n")
    sys.stderr.flush()

    baseline_decision = ensure_baseline(manifest_path, run_dir, args.strategy, cwd)
    sys.stderr.write(
        f"[auto] Baseline decision={baseline_decision.get('decision', '?')} "
        f"reasons={baseline_decision.get('decision_reasons', [])}\n"
    )
    sys.stderr.flush()
    last_payload: Dict[str, Any] = {"baseline": baseline_decision}
    completed_rounds = count_completed_rounds(run_dir)
    start_round = completed_rounds + 1
    configured_round_retries = manifest.get("execution", {}).get("round_retry", {}).get("max_attempts", 2)
    round_retries = args.round_retries if args.round_retries is not None else int(configured_round_retries or 2)

    if completed_rounds:
        sys.stderr.write(
            f"[auto] Resuming run: {completed_rounds} completed round(s), "
            f"starting at round {start_round}.\n"
        )
        sys.stderr.flush()

    for index in range(start_round, args.rounds + 1):
        round_ok = False
        sys.stderr.write(f"\n[auto] ===== Round {index}/{args.rounds} =====\n")
        sys.stderr.flush()
        for attempt in range(1, round_retries + 1):
            update_supervisor(
                run_dir,
                status="advancing_candidate",
                next_action=f"auto round {index} attempt {attempt}/{round_retries}",
                auto_round=index,
                auto_round_attempt=attempt,
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
            try:
                sys.stderr.write(f"[auto] Round {index}/{args.rounds}, attempt {attempt}/{round_retries}: advance\n")
                sys.stderr.flush()
                payload = run_json_command(command, cwd)
                last_payload = payload
                round_ok = True
                sys.stderr.write(
                    f"[auto] Round {index} complete: candidate={payload.get('candidate_id', '?')} "
                    f"packet={payload.get('packet_id', '?')} "
                    f"decision={payload.get('candidate', {}).get('decision', '?')}\n"
                )
                sys.stderr.flush()
                break
            except Exception as exc:
                sys.stderr.write(f"[auto] Round {index} attempt {attempt} failed: {exc}\n")
                sys.stderr.flush()

        if not round_ok:
            run_state_path = run_dir / "run-state.json"
            run_state = read_json(run_state_path)
            counters = run_state.setdefault("counters", {"keeps": 0, "discards": 0, "crashes": 0})
            counters["crashes"] = int(counters.get("crashes", 0) or 0) + 1
            write_json(run_state_path, run_state)
            update_supervisor(run_dir, status="round_crashed", auto_round=index)
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
