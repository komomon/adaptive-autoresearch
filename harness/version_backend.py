#!/usr/bin/env python3
"""
Candidate workspace preparation and run-state wiring.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

from _shared import append_jsonl, read_json, run_subprocess, write_json


def detect_git_root(repo_path: Path) -> Path | None:
    if not repo_path.exists():
        return None
    probe = run_subprocess(["git", "rev-parse", "--show-toplevel"], repo_path)
    if probe.returncode != 0:
        return None
    resolved = probe.stdout.strip()
    return Path(resolved).resolve() if resolved else None


def candidate_root(run_dir: Path) -> Path:
    return run_dir / "candidates"


def candidate_dir(run_dir: Path, candidate_id: str) -> Path:
    return candidate_root(run_dir) / candidate_id


def candidate_workspace_dir(run_dir: Path, candidate_id: str) -> Path:
    return candidate_dir(run_dir, candidate_id) / "workspace"


def candidate_metadata_path(run_dir: Path, candidate_id: str) -> Path:
    return candidate_dir(run_dir, candidate_id) / "candidate.json"


def read_candidate_metadata(run_dir: Path, candidate_id: str) -> Dict[str, Any] | None:
    path = candidate_metadata_path(run_dir, candidate_id)
    if not path.exists():
        return None
    return read_json(path)


def resolve_candidate_reference(run_state: Dict[str, Any], reference: str) -> str:
    if reference == "best":
        return str(run_state.get("best", {}).get("candidate_id", "baseline"))
    if reference == "baseline":
        return str(run_state.get("baseline", {}).get("candidate_id", "baseline"))
    if reference == "current":
        return str(run_state.get("current", {}).get("candidate_id", "baseline"))
    return reference


def source_workspace_for_candidate(
    manifest: Dict[str, Any],
    run_dir: Path,
    run_state: Dict[str, Any],
    source_reference: str,
) -> tuple[Path, str]:
    resolved_source = resolve_candidate_reference(run_state, source_reference)
    if resolved_source == "baseline":
        return Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve(), resolved_source
    source_workspace = candidate_workspace_dir(run_dir, resolved_source)
    if source_workspace.exists():
        return source_workspace, resolved_source
    return Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve(), resolved_source


def effective_version_backend(manifest: Dict[str, Any]) -> str:
    configured = str(manifest.get("experiment", {}).get("versioning", {}).get("backend", "local-dir"))
    repo_path = Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve()
    if configured == "git" and detect_git_root(repo_path) is not None:
        return "git"
    return "local-dir"


def snapshot_copytree(source: Path, destination: Path) -> None:
    ignore = shutil.ignore_patterns(
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
    )
    shutil.copytree(source, destination, ignore=ignore)


def prepare_candidate_workspace(
    manifest: Dict[str, Any],
    run_dir: Path,
    candidate_id: str,
    source_reference: str,
) -> Dict[str, Any]:
    run_state = read_json(run_dir / "run-state.json")
    workspace_path = candidate_workspace_dir(run_dir, candidate_id)
    if workspace_path.exists():
        metadata = read_json(candidate_metadata_path(run_dir, candidate_id))
        activate_candidate_workspace(run_dir, candidate_id, workspace_path, metadata.get("source_candidate_id", source_reference))
        return metadata

    source_workspace, resolved_source = source_workspace_for_candidate(
        manifest,
        run_dir,
        run_state,
        source_reference,
    )
    workspace_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_copytree(source_workspace, workspace_path)

    repo_path = Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve()
    metadata = {
        "candidate_id": candidate_id,
        "source_candidate_id": resolved_source,
        "source_workspace_path": str(source_workspace),
        "workspace_path": str(workspace_path),
        "configured_backend": str(manifest.get("experiment", {}).get("versioning", {}).get("backend", "local-dir")),
        "effective_backend": effective_version_backend(manifest),
        "source_git_root": str(detect_git_root(repo_path) or ""),
    }
    write_json(candidate_metadata_path(run_dir, candidate_id), metadata)
    append_jsonl(
        run_dir / "candidate-ledger.jsonl",
        {
            "event": "candidate_workspace_prepared",
            **metadata,
        },
    )
    activate_candidate_workspace(run_dir, candidate_id, workspace_path, resolved_source)
    return metadata


def activate_candidate_workspace(
    run_dir: Path,
    candidate_id: str,
    workspace_path: Path,
    source_candidate_id: str,
) -> Dict[str, Any]:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state.setdefault("current", {})
    run_state["current"]["candidate_id"] = candidate_id
    run_state["current"]["target_project"] = {
        "candidate_id": candidate_id,
        "workspace_path": str(workspace_path.resolve()),
        "source_candidate_id": source_candidate_id,
    }
    write_json(run_state_path, run_state)
    return run_state


def next_candidate_id(run_dir: Path) -> str:
    root = candidate_root(run_dir)
    if not root.exists():
        return "candidate-0001"
    max_index = 0
    for item in root.iterdir():
        if not item.is_dir():
            continue
        name = item.name
        if not name.startswith("candidate-"):
            continue
        suffix = name.split("candidate-", 1)[1]
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return f"candidate-{max_index + 1:04d}"
