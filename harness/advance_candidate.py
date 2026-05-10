#!/usr/bin/env python3
"""
Prepare, propose, apply, and evaluate one new candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _shared import load_manifest, read_json, run_json_command, update_supervisor
from version_backend import next_candidate_id


class AdvanceStageError(RuntimeError):
    def __init__(self, stage: str, message: str, candidate_id: str = "", packet_id: str = ""):
        self.stage = stage
        self.candidate_id = candidate_id
        self.packet_id = packet_id
        super().__init__(f"[{stage}] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Advance autoresearch by one candidate.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", help="Optional explicit candidate id.")
    parser.add_argument("--source", default="best", help="Source candidate reference. Defaults to best.")
    parser.add_argument("--split", default="dev", help="Failure split to inspect. Defaults to dev.")
    parser.add_argument("--strategy", choices=("staged", "full"), help="Optional evaluation strategy override.")
    return parser.parse_args()


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

    try:
        update_supervisor(
            run_dir,
            status="preparing_candidate_workspace",
            next_action="prepare workspace",
            active_candidate_id=candidate_id,
        )
        sys.stderr.write(f"[advance] Preparing workspace for {candidate_id} from {args.source}\n")
        sys.stderr.flush()
        prepare_payload = run_json_command(
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
        sys.stderr.write(
            f"[advance] Workspace prepared: source_candidate_id={prepare_payload.get('source_candidate_id', '?')}\n"
        )
        sys.stderr.flush()
    except Exception as exc:
        update_supervisor(run_dir, status="stage_failed", failed_stage="prepare")
        raise AdvanceStageError("prepare", str(exc), candidate_id, packet_id) from exc

    try:
        update_supervisor(
            run_dir,
            status="proposing_packet",
            next_action="propose packet",
            active_packet_id=packet_id,
        )
        sys.stderr.write(f"[advance] Proposing packet {packet_id}\n")
        sys.stderr.flush()
        packet_payload = run_json_command(
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
        sys.stderr.write(f"[advance] Packet proposed: {packet_path}\n")
        sys.stderr.flush()
    except Exception as exc:
        update_supervisor(run_dir, status="stage_failed", failed_stage="propose", active_packet_id=packet_id)
        raise AdvanceStageError("propose", str(exc), candidate_id, packet_id) from exc

    try:
        update_supervisor(
            run_dir,
            status="applying_packet",
            next_action="apply packet",
            active_packet_id=packet_id,
        )
        sys.stderr.write(f"[advance] Applying packet {packet_id} to {candidate_id}\n")
        sys.stderr.flush()
        apply_payload = run_json_command(
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
        sys.stderr.write(f"[advance] Packet applied: modified_files={apply_payload.get('modified_files', [])}\n")
        sys.stderr.flush()
    except Exception as exc:
        update_supervisor(run_dir, status="stage_failed", failed_stage="apply", active_packet_id=packet_id)
        raise AdvanceStageError("apply", str(exc), candidate_id, packet_id) from exc

    try:
        update_supervisor(
            run_dir,
            status="evaluating_candidate",
            next_action="run candidate evaluation",
            active_packet_id=packet_id,
        )
        sys.stderr.write(f"[advance] Evaluating candidate {candidate_id}\n")
        sys.stderr.flush()
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
        candidate_payload = run_json_command(candidate_command, cwd)
        append_lesson_entry(run_dir, packet_id, candidate_id)
        sys.stderr.write(
            f"[advance] Evaluation done: decision={candidate_payload.get('decision', '?')} "
            f"reasons={candidate_payload.get('decision_reasons', [])}\n"
        )
        sys.stderr.flush()
    except Exception as exc:
        update_supervisor(run_dir, status="stage_failed", failed_stage="evaluate", active_packet_id=packet_id)
        raise AdvanceStageError("evaluate", str(exc), candidate_id, packet_id) from exc

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
