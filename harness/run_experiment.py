#!/usr/bin/env python3
"""
Initialize a reproducible autoresearch run from a manifest and normalized cases.

This is intentionally a control-plane skeleton:
- it creates run metadata and split files
- it prepares run/state/scoreboard ledgers
- it does not yet call the target audit system or grader
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize an autoresearch experiment run.")
    parser.add_argument("--manifest", required=True, help="Path to the eval manifest yaml.")
    parser.add_argument(
        "--normalized-cases",
        help="Optional override for normalized jsonl path. Defaults to dataset.normalize_to in manifest.",
    )
    return parser.parse_args()


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
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return data


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
                raise SystemExit(f"Invalid JSON in normalized cases line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"Invalid case payload on line {line_number}: must be an object.")
            rows.append(payload)
    return rows


def stable_bucket(case_id: str) -> int:
    digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10000


def assign_split(case_id: str, split_config: Dict[str, Any]) -> str:
    bucket = stable_bucket(case_id)
    dev_max = int(float(split_config.get("dev", 0.50)) * 10000)
    holdout_max = dev_max + int(float(split_config.get("holdout", 0.25)) * 10000)
    cross_repo_max = holdout_max + int(float(split_config.get("cross_repo", 0.15)) * 10000)
    if bucket < dev_max:
        return "dev"
    if bucket < holdout_max:
        return "holdout"
    if bucket < cross_repo_max:
        return "cross_repo"
    return "canary"


def build_run_id(experiment_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    normalized = experiment_name.replace(" ", "-")
    return f"{normalized}-{stamp}"


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def initialize_scoreboard() -> Dict[str, Any]:
    blank_split = {
        "accuracy": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "evidence_adequacy": 0.0,
        "chain_completeness": 0.0,
        "high_confidence_false_positive_rate": 0.0,
        "case_count": 0,
    }
    blank_candidate = {
        "candidate_id": "baseline",
        "splits": {
            "dev": dict(blank_split),
            "holdout": dict(blank_split),
            "cross_repo": dict(blank_split),
            "canary": dict(blank_split),
        },
    }
    return {
        "baseline": dict(blank_candidate),
        "best": dict(blank_candidate),
        "current": dict(blank_candidate),
    }


def initialize_run_state(
    run_id: str,
    profile: str,
    topology: str,
    version_backend: str,
    target_repo_path: str,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "baseline": {
            "candidate_id": "baseline",
            "target_project": {
                "candidate_id": "baseline",
                "workspace_path": target_repo_path,
                "source_candidate_id": "baseline",
            },
        },
        "best": {
            "candidate_id": "baseline",
            "target_project": {
                "candidate_id": "baseline",
                "workspace_path": target_repo_path,
                "source_candidate_id": "baseline",
            },
        },
        "current": {
            "candidate_id": "baseline",
            "target_project": {
                "candidate_id": "baseline",
                "workspace_path": target_repo_path,
                "source_candidate_id": "baseline",
            },
        },
        "counters": {"keeps": 0, "discards": 0, "crashes": 0},
        "lessons_pointer": "lesson-ledger.md",
        "active_profile": profile,
        "active_topology": topology,
        "version_backend": version_backend,
        "scoreboard_pointer": "scoreboard.json",
        "supervisor": {
            "status": "initialized",
            "next_action": "run baseline on dev split",
        },
    }


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)

    experiment = manifest.get("experiment", {})
    dataset = manifest.get("dataset", {})
    execution = manifest.get("execution", {})
    outputs = manifest.get("outputs", {})

    normalized_raw = args.normalized_cases or dataset.get("normalize_to", "")
    if not normalized_raw:
        raise SystemExit("Missing normalized cases: set dataset.normalize_to in manifest or pass --normalized-cases.")
    normalized_path = Path(normalized_raw).resolve()
    if not normalized_path.exists():
        raise SystemExit(f"Normalized cases file not found: {normalized_path}")

    cases = read_jsonl(normalized_path)
    split_config = dataset.get("split", {})
    run_root = Path(outputs.get("run_root", "./autoresearch-results")).resolve()
    run_id = build_run_id(experiment.get("name", "autoresearch-run"))
    run_dir = run_root / "runs" / run_id

    split_rows: Dict[str, List[Dict[str, Any]]] = {
        "dev": [],
        "holdout": [],
        "cross_repo": [],
        "canary": [],
    }
    for case in cases:
        case_id = str(case.get("case_id"))
        split_name = assign_split(case_id, split_config)
        split_rows[split_name].append(case)

    for split_name, rows in split_rows.items():
        write_jsonl(run_dir / "splits" / f"{split_name}.jsonl", rows)

    scoreboard = initialize_scoreboard()
    for split_name, rows in split_rows.items():
        scoreboard["baseline"]["splits"][split_name]["case_count"] = len(rows)
        scoreboard["best"]["splits"][split_name]["case_count"] = len(rows)
        scoreboard["current"]["splits"][split_name]["case_count"] = len(rows)

    versioning = experiment.get("versioning", {})
    version_backend = versioning.get("backend", "git")
    default_topology = execution.get("topology", {}).get("default", "S1")
    profile = experiment.get("profile", "generic-vuln-audit")

    run_state = initialize_run_state(
        run_id=run_id,
        profile=profile,
        topology=default_topology,
        version_backend=version_backend,
        target_repo_path=str(Path(str(experiment.get("target_project", {}).get("repo_path", "."))).resolve()),
    )

    write_json(run_dir / "run-state.json", run_state)
    write_json(run_dir / "scoreboard.json", scoreboard)
    write_json(
        run_dir / "manifest.snapshot.json",
        {
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "normalized_cases_path": str(normalized_path),
            "split_counts": {name: len(rows) for name, rows in split_rows.items()},
        },
    )
    (run_dir / "lesson-ledger.md").write_text("# Lesson Ledger\n\n", encoding="utf-8")
    (run_dir / "candidate-ledger.jsonl").write_text("", encoding="utf-8")

    print(f"Initialized run {run_id}")
    print(f"Run dir: {run_dir}")
    print("Split counts:")
    for split_name, rows in split_rows.items():
        print(f"  {split_name}: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
