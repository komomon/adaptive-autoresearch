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

from _shared import count_completed_rounds, cleanup_incomplete_round, read_json, run_subprocess, update_supervisor, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full autoresearch loop.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", help="Optional existing run directory. If omitted, a new run is initialized.")
    parser.add_argument("--rounds", type=int, default=3, help="Maximum auto-optimization rounds to run.")
    parser.add_argument("--strategy", choices=("staged", "full"), help="Optional candidate evaluation strategy override.")
    return parser.parse_args()


def run_json_command(command: list[str], cwd: Path) -> Dict[str, Any]:
    result = run_subprocess(command, cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\ncommand={' '.join(command)}\nstdout={result.stdout}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"stdout": result.stdout}


def initialize_run(manifest_path: Path, cwd: Path) -> Path:
    command = [
        sys.executable,
        str((Path(__file__).resolve().parent / "run_experiment.py").resolve()),
        "--manifest",
        str(manifest_path),
    ]
    result = run_subprocess(command, cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"run_experiment failed:\nstdout={result.stdout}"
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
    cwd = Path.cwd()

    # ── Phase 1: initialize run ──────────────────────────────────────────
    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        print(f"[auto] Using existing run dir: {run_dir}", file=sys.stderr, flush=True)
    else:
        print("[auto] Initializing new run ...", file=sys.stderr, flush=True)
        run_dir = initialize_run(manifest_path, cwd)
        print(f"[auto] Run dir: {run_dir}", file=sys.stderr, flush=True)

    # ── Phase 2: establish baseline ──────────────────────────────────────
    baseline_decision_path = run_dir / "decisions" / "baseline.decision.json"
    if baseline_decision_path.exists():
        print("[auto] Baseline already exists, skipping.", file=sys.stderr, flush=True)
    else:
        print("[auto] Running baseline evaluation ...", file=sys.stderr, flush=True)
    baseline_decision = ensure_baseline(manifest_path, run_dir, args.strategy, cwd)
    print(
        f"[auto] Baseline decision: {baseline_decision.get('decision', '?')} | "
        f"reasons: {', '.join(baseline_decision.get('decision_reasons', []))}",
        file=sys.stderr,
        flush=True,
    )

    last_payload: Dict[str, Any] = {"baseline": baseline_decision}

    # ── Phase 3: advance candidates ──────────────────────────────────────
    completed = count_completed_rounds(run_dir)
    cleanup_incomplete_round(run_dir)
    start_round = completed + 1

    if completed > 0:
        print(
            f"[auto] Resuming: {completed} round(s) already completed. "
            f"Starting from round {start_round}.",
            file=sys.stderr, flush=True,
        )

    new_rounds = max(0, args.rounds - completed)
    max_round_retries = 2

    for index in range(start_round, args.rounds + 1):
        print(f"\n{'='*60}", file=sys.stderr, flush=True)
        print(f"[auto] === Round {index}/{args.rounds} ===", file=sys.stderr, flush=True)
        print(f"{'='*60}", file=sys.stderr, flush=True)

        round_ok = False
        for attempt in range(1, max_round_retries + 1):
            try:
                cleanup_incomplete_round(run_dir)
                update_supervisor(
                    run_dir,
                    status="advancing_candidate",
                    next_action=f"auto round {index} attempt {attempt}/{max_round_retries}",
                    auto_round=index,
                )
                command = [
                    sys.executable,
                    str((Path(__file__).resolve().parent / "advance_candidate.py").resolve()),
                    "--manifest", str(manifest_path),
                    "--run-dir", str(run_dir),
                ]
                if args.strategy:
                    command.extend(["--strategy", args.strategy])

                print(
                    f"[auto] Advancing candidate (attempt {attempt}/{max_round_retries}) ...",
                    file=sys.stderr, flush=True,
                )
                payload = run_json_command(command, cwd)
                last_payload = payload
                round_ok = True
                break
            except Exception as exc:
                print(
                    f"[auto] Round {index} attempt {attempt}/{max_round_retries} FAILED: {exc}",
                    file=sys.stderr, flush=True,
                )
                if attempt < max_round_retries:
                    print(f"[auto] Retrying round {index} ...", file=sys.stderr, flush=True)

        if not round_ok:
            update_supervisor(run_dir, status="round_crashed", auto_round=index)
            run_state_path = run_dir / "run-state.json"
            run_state = read_json(run_state_path)
            counters = run_state.setdefault("counters", {"keeps": 0, "discards": 0, "crashes": 0})
            counters["crashes"] = int(counters.get("crashes", 0) or 0) + 1
            write_json(run_state_path, run_state)
            print(
                f"[auto] Round {index} CRASHED after {max_round_retries} attempts. "
                f"Continuing to next round.",
                file=sys.stderr, flush=True,
            )
            continue

        candidate_id = payload.get("candidate_id", "?")
        packet_id = payload.get("packet_id", "?")
        candidate_decision = payload.get("candidate", {}).get("decision", "?")
        reasons = payload.get("candidate", {}).get("decision_reasons", [])

        print(
            f"[auto] Round {index} complete: candidate={candidate_id} "
            f"packet={packet_id} decision={candidate_decision} "
            f"reasons={reasons}",
            file=sys.stderr,
            flush=True,
        )
        if candidate_decision == "keep":
            continue

    # ── Phase 4: done ────────────────────────────────────────────────────
    update_supervisor(
        run_dir,
        status="auto_loop_completed",
        next_action="inspect best candidate and lessons",
    )
    print(f"\n[auto] All rounds finished ({completed} resumed, {new_rounds} new).", file=sys.stderr, flush=True)
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
