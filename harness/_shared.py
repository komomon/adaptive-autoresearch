#!/usr/bin/env python3
"""
Shared harness utilities.

This module intentionally contains only low-risk helpers. It does not delete
candidate, packet, grading, or target-result artifacts; failed run state should
remain available for debugging unless a user explicitly asks for cleanup.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List


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


def run_subprocess(
    command: List[str],
    cwd: Path,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Subprocess timed out after {timeout_seconds} seconds:\n"
            f"command={' '.join(command)}\n"
            f"stdout={exc.stdout or ''}\n"
            f"stderr={exc.stderr or ''}"
        ) from exc


def run_json_command(command: List[str], cwd: Path) -> Dict[str, Any]:
    result = run_subprocess(command, cwd)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed:\ncommand={' '.join(command)}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(
            f"Subprocess produced no output.\ncommand={' '.join(command)}\n"
            f"stderr={result.stderr}"
        )
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Subprocess last output line is not JSON.\ncommand={' '.join(command)}\n"
            f"last_line={lines[-1]}\nstderr={result.stderr}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Subprocess returned non-object JSON.\ncommand={' '.join(command)}\n"
            f"last_line={lines[-1]}"
        )
    return payload


def update_supervisor(run_dir: Path, **fields: object) -> None:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state.setdefault("supervisor", {})
    run_state["supervisor"].update(fields)
    write_json(run_state_path, run_state)


def count_completed_rounds(run_dir: Path) -> int:
    decisions_dir = run_dir / "decisions"
    if not decisions_dir.exists():
        return 0
    return sum(
        1
        for item in decisions_dir.iterdir()
        if item.name.endswith(".decision.json") and item.name != "baseline.decision.json"
    )
