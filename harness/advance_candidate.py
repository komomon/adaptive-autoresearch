#!/usr/bin/env python3
"""
Prepare, propose, apply, and evaluate one new candidate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from run_experiment import load_manifest
from version_backend import next_candidate_id, read_json, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Advance autoresearch by one candidate.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", help="Optional explicit candidate id.")
    parser.add_argument("--source", default="best", help="Source candidate reference. Defaults to best.")
    parser.add_argument("--split", default="dev", help="Failure split to inspect. Defaults to dev.")
    parser.add_argument("--strategy", choices=("staged", "full"), help="Optional evaluation strategy override.")
    return parser.parse_args()


def run_subprocess(command: list[str], cwd: Path) -> dict:
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
    return json.loads(result.stdout.strip().splitlines()[-1])


def next_packet_id(run_dir: Path) -> str:
    packets_dir = run_dir / "packets"
    if not packets_dir.exists():
        return "packet-0001"
    max_index = 0
    for item in packets_dir.iterdir():
        if not item.is_dir():
            continue
        if not item.name.startswith("packet-"):
            continue
        suffix = item.name.split("packet-", 1)[1]
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return f"packet-{max_index + 1:04d}"


def update_supervisor(run_dir: Path, **fields: object) -> None:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state.setdefault("supervisor", {})
    run_state["supervisor"].update(fields)
    write_json(run_state_path, run_state)


def append_lesson_entry(run_dir: Path, packet_id: str, candidate_id: str) -> None:
    packet_path = run_dir / "packets" / packet_id / "packet.json"
    decision_path = run_dir / "decisions" / f"{candidate_id}.decision.json"
    scoreboard_path = run_dir / "scoreboard.json"
    if not packet_path.exists() or not decision_path.exists() or not scoreboard_path.exists():
        return

    packet = read_json(packet_path)
    decision = read_json(decision_path)
    scoreboard = read_json(scoreboard_path)
    current_dev = scoreboard.get("current", {}).get("splits", {}).get("dev", {})
    best_dev = scoreboard.get("best", {}).get("splits", {}).get("dev", {})

    lines = [
        f"## {candidate_id} / {packet_id}",
        "",
        f"- primary_axis: {packet.get('primary_axis', '')}",
        f"- decision: {decision.get('decision', '')}",
        f"- summary: {packet.get('summary', '')}",
        f"- failure_hypothesis: {packet.get('failure_hypothesis', '')}",
        f"- dev_current_f1: {current_dev.get('f1', 0.0)}",
        f"- dev_best_f1: {best_dev.get('f1', 0.0)}",
        f"- dev_current_evidence_adequacy: {current_dev.get('evidence_adequacy', 0.0)}",
        f"- decision_reasons: {', '.join(decision.get('decision_reasons', []))}",
        f"- modified_files: {', '.join(read_json(run_dir / 'packets' / packet_id / 'apply-result.json').get('modified_files', [])) if (run_dir / 'packets' / packet_id / 'apply-result.json').exists() else ''}",
        "",
    ]
    with (run_dir / "lesson-ledger.md").open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    _manifest = load_manifest(manifest_path)
    run_dir = Path(args.run_dir).resolve()
    candidate_id = args.candidate_id or next_candidate_id(run_dir)
    packet_id = next_packet_id(run_dir)
    cwd = Path.cwd()

    update_supervisor(
        run_dir,
        status="preparing_candidate_workspace",
        next_action="prepare workspace",
        active_candidate_id=candidate_id,
    )
    prepare_payload = run_subprocess(
        [
            sys.executable,
            str((Path(__file__).resolve().parent / "prepare_candidate.py").resolve()),
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
            "--candidate-id",
            candidate_id,
            "--source",
            args.source,
        ],
        cwd,
    )

    update_supervisor(
        run_dir,
        status="proposing_packet",
        next_action="propose packet",
        active_packet_id=packet_id,
    )
    packet_payload = run_subprocess(
        [
            sys.executable,
            str((Path(__file__).resolve().parent / "propose_packet.py").resolve()),
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
            "--candidate-id",
            prepare_payload["source_candidate_id"],
            "--split",
            args.split,
            "--packet-id",
            packet_id,
        ],
        cwd,
    )
    packet_path = Path(packet_payload["packet_path"]).resolve()

    update_supervisor(
        run_dir,
        status="applying_packet",
        next_action="apply packet",
        active_packet_id=packet_id,
    )
    apply_payload = run_subprocess(
        [
            sys.executable,
            str((Path(__file__).resolve().parent / "apply_packet.py").resolve()),
            "--manifest",
            str(manifest_path),
            "--run-dir",
            str(run_dir),
            "--candidate-id",
            candidate_id,
            "--packet-file",
            str(packet_path),
        ],
        cwd,
    )

    update_supervisor(
        run_dir,
        status="evaluating_candidate",
        next_action="run candidate evaluation",
        active_packet_id=packet_id,
    )
    candidate_command = [
        sys.executable,
        str((Path(__file__).resolve().parent / "run_candidate.py").resolve()),
        "--manifest",
        str(manifest_path),
        "--run-dir",
        str(run_dir),
        "--candidate-id",
        candidate_id,
    ]
    if args.strategy:
        candidate_command.extend(["--strategy", args.strategy])
    candidate_payload = run_subprocess(candidate_command, cwd)
    append_lesson_entry(run_dir, packet_id, candidate_id)

    print(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "packet_id": packet_id,
                "packet_path": str(packet_path),
                "prepare": prepare_payload,
                "apply": apply_payload,
                "candidate": candidate_payload,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
