#!/usr/bin/env python3
"""
Shared I/O and utility functions for the autoresearch harness.

All harness scripts should import common utilities from this module
instead of defining local copies.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List


# ── JSON I/O ──────────────────────────────────────────────────────


def read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid JSON object in {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON in {path} line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"Invalid object in {path} line {line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ── Subprocess ───────────────────────────────────────────────────


def run_subprocess(command: List[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing stdout only; stderr passes through to terminal."""
    return subprocess.run(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        encoding="utf-8",
    )


# ── YAML ──────────────────────────────────────────────────────────


def require_yaml():
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML is required to read the manifest. Install it before running this script."
        ) from exc
    return yaml


def load_manifest(path: Path) -> Dict[str, Any]:
    yaml = require_yaml()
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return payload


# ── Scoring ───────────────────────────────────────────────────────


def blank_split_score(case_count: int = 0) -> Dict[str, Any]:
    return {
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "evidence_adequacy": 0.0,
        "chain_completeness": 0.0,
        "high_confidence_false_positive_rate": 0.0,
        "case_count": case_count,
    }


# ── LLM output parsing ───────────────────────────────────────────


def parse_json_object(text: str, context_label: str = "LLM output") -> Dict[str, Any]:
    """Extract a JSON object from LLM text output."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    # Try fenced code blocks
    for match in re.finditer(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL):
        block = match.group(1).strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    # Try outermost braces
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"{context_label} did not return a parseable JSON object.")


# ── Audit result shaping ─────────────────────────────────────────


def ensure_target_result_shape(case: Dict[str, Any], payload: Dict[str, Any], raw_output_ref: str) -> Dict[str, Any]:
    payload.setdefault("case_id", case.get("case_id"))
    payload.setdefault(
        "entry",
        {
            "name": case.get("entry", {}).get("name"),
            "transport": case.get("entry", {}).get("transport"),
            "language": case.get("entry", {}).get("language"),
        },
    )
    payload.setdefault(
        "verdict",
        {
            "has_vulnerability": False,
            "status": "unknown",
            "confidence": 0.0,
            "summary": "",
        },
    )
    payload.setdefault(
        "evidence",
        {
            "files": [],
            "functions": [],
            "locations": [],
            "reasoning_mode": "report-derived",
            "notes": [],
        },
    )
    payload.setdefault("artifacts", {})
    payload["raw_output_ref"] = raw_output_ref
    return payload


# ── State management ──────────────────────────────────────────────


def update_supervisor(run_dir: Path, **fields: object) -> None:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state.setdefault("supervisor", {})
    run_state["supervisor"].update(fields)
    write_json(run_state_path, run_state)


# ── Round-level resume ────────────────────────────────────────────


def count_completed_rounds(run_dir: Path) -> int:
    """Count completed non-baseline rounds by counting decision files."""
    decisions_dir = run_dir / "decisions"
    if not decisions_dir.exists():
        return 0
    return sum(
        1 for f in decisions_dir.iterdir()
        if f.name.endswith(".decision.json") and f.name != "baseline.decision.json"
    )


def cleanup_incomplete_round(run_dir: Path) -> None:
    """Remove artifacts from an incomplete round (candidate without decision)."""
    import shutil

    # Build set of completed candidate IDs (those with decision files)
    complete_ids: set[str] = set()
    decisions_dir = run_dir / "decisions"
    if decisions_dir.exists():
        for f in decisions_dir.iterdir():
            if f.name.endswith(".decision.json"):
                complete_ids.add(f.name.rsplit(".decision.json", 1)[0])

    # Remove incomplete candidate dirs and their target-results/grading
    candidates_dir = run_dir / "candidates"
    if candidates_dir.exists():
        for item in list(candidates_dir.iterdir()):
            if not item.is_dir() or not item.name.startswith("candidate-"):
                continue
            if item.name in complete_ids:
                continue
            cid = item.name
            shutil.rmtree(item, ignore_errors=True)
            for subdir in ("target-results", "grading"):
                t = run_dir / subdir / cid
                if t.exists():
                    shutil.rmtree(t, ignore_errors=True)

    # Remove orphaned packets whose target candidate is not complete
    packets_dir = run_dir / "packets"
    if packets_dir.exists():
        for pkt in list(packets_dir.iterdir()):
            if not pkt.is_dir():
                continue
            ar = pkt / "apply-result.json"
            if ar.exists():
                # apply-result.json stores the target candidate_id reliably
                try:
                    cid = read_json(ar).get("candidate_id", "")
                except Exception:
                    cid = ""
                if not cid or cid not in complete_ids:
                    shutil.rmtree(pkt, ignore_errors=True)
            elif (pkt / "packet.json").exists():
                # Packet proposed but never applied — orphaned
                shutil.rmtree(pkt, ignore_errors=True)
