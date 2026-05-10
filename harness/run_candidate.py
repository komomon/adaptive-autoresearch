#!/usr/bin/env python3
"""
Run one candidate version across the configured splits and decide keep/discard.

This is the candidate-level control-plane entry:
- it delegates split execution to run_packet.py
- it compares the candidate against the current best version
- it updates scoreboard/run-state/decision ledgers

It intentionally does not mutate the target project itself. The target project
version is assumed to already be prepared before this script runs.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from version_backend import read_candidate_metadata


EPS = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one candidate version.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Run directory initialized by run_experiment.py.")
    parser.add_argument("--candidate-id", required=True, help="Candidate version identifier.")
    parser.add_argument(
        "--strategy",
        choices=("staged", "full"),
        help="Optional evaluation strategy override. Defaults to execution.candidate_evaluation.strategy or staged.",
    )
    parser.add_argument("--limit-dev", type=int, help="Optional case limit for dev split.")
    parser.add_argument("--limit-holdout", type=int, help="Optional case limit for holdout split.")
    parser.add_argument("--limit-cross-repo", type=int, help="Optional case limit for cross_repo split.")
    parser.add_argument("--limit-canary", type=int, help="Optional case limit for canary split.")
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
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return payload


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_subprocess(command: List[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def default_run_packet_script() -> Path:
    return (Path(__file__).resolve().parent / "run_packet.py").resolve()


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


def prepare_current_candidate(scoreboard: Dict[str, Any], candidate_id: str) -> Dict[str, Any]:
    baseline = scoreboard.get("baseline", {})
    baseline_splits = baseline.get("splits", {})
    current = {
        "candidate_id": candidate_id,
        "splits": {
            split: blank_split_score(int(baseline_splits.get(split, {}).get("case_count", 0) or 0))
            for split in ("dev", "holdout", "cross_repo", "canary")
        },
    }
    scoreboard["current"] = current
    return scoreboard


def candidate_target_project_payload(run_dir: Path, run_state: Dict[str, Any], candidate_id: str) -> Dict[str, Any] | None:
    current_target = run_state.get("current", {}).get("target_project")
    if isinstance(current_target, dict) and current_target.get("candidate_id") == candidate_id:
        return current_target

    metadata = read_candidate_metadata(run_dir, candidate_id)
    if isinstance(metadata, dict):
        workspace_path = metadata.get("workspace_path")
        if workspace_path:
            return {
                "candidate_id": candidate_id,
                "workspace_path": str(Path(str(workspace_path)).resolve()),
                "source_candidate_id": metadata.get("source_candidate_id", candidate_id),
            }

    candidate_workspace = run_dir / "candidates" / candidate_id / "workspace"
    if candidate_workspace.exists():
        return {
            "candidate_id": candidate_id,
            "workspace_path": str(candidate_workspace.resolve()),
            "source_candidate_id": candidate_id,
        }

    if candidate_id == "baseline":
        baseline_target = run_state.get("baseline", {}).get("target_project")
        if isinstance(baseline_target, dict):
            return baseline_target
    return None


def set_run_state_current(run_state: Dict[str, Any], candidate_id: str, strategy: str, run_dir: Path) -> Dict[str, Any]:
    target_project = candidate_target_project_payload(run_dir, run_state, candidate_id)
    run_state["current"] = {"candidate_id": candidate_id}
    if isinstance(target_project, dict):
        run_state["current"]["target_project"] = target_project
    run_state.setdefault("supervisor", {})
    run_state["supervisor"]["status"] = "candidate_running"
    run_state["supervisor"]["active_candidate_id"] = candidate_id
    run_state["supervisor"]["evaluation_strategy"] = strategy
    run_state["supervisor"]["next_action"] = "run dev split"
    return run_state


def target_project_revision(manifest: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    target_project = manifest.get("experiment", {}).get("target_project", {})
    run_state_path = run_dir / "run-state.json"
    repo_path = Path(target_project.get("repo_path", ".")).resolve()
    if run_state_path.exists():
        try:
            run_state = read_json(run_state_path)
            current_target = run_state.get("current", {}).get("target_project", {})
            workspace_path = current_target.get("workspace_path")
            if workspace_path:
                repo_path = Path(str(workspace_path)).resolve()
        except Exception:
            pass
    if not repo_path.exists():
        return {
            "backend": "unknown",
            "repo_path": str(repo_path),
            "exists": False,
        }
    git_probe = run_subprocess(["git", "rev-parse", "--show-toplevel"], repo_path)
    if git_probe.returncode == 0:
        head = run_subprocess(["git", "rev-parse", "HEAD"], repo_path)
        branch = run_subprocess(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
        return {
            "backend": "git",
            "repo_path": str(repo_path),
            "git_root": git_probe.stdout.strip(),
            "head": head.stdout.strip() if head.returncode == 0 else "",
            "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        }
    return {
        "backend": "local-dir",
        "repo_path": str(repo_path),
    }


def split_case_count(scoreboard: Dict[str, Any], split: str) -> int:
    return int(scoreboard.get("baseline", {}).get("splits", {}).get(split, {}).get("case_count", 0) or 0)


def split_score(candidate: Dict[str, Any], split: str) -> Dict[str, Any]:
    return candidate.get("splits", {}).get(split, {})


def float_metric(score: Dict[str, Any], key: str) -> float:
    return float(score.get(key, 0.0) or 0.0)


def is_baseline(candidate_id: str) -> bool:
    return candidate_id == "baseline"


def dev_improved(candidate: Dict[str, Any], reference: Dict[str, Any]) -> Tuple[bool, str]:
    cand = split_score(candidate, "dev")
    ref = split_score(reference, "dev")
    cand_f1 = float_metric(cand, "f1")
    ref_f1 = float_metric(ref, "f1")
    if cand_f1 > ref_f1 + EPS:
        return True, "dev.f1 improved"

    cand_recall = float_metric(cand, "recall")
    ref_recall = float_metric(ref, "recall")
    if abs(cand_f1 - ref_f1) <= EPS and cand_recall > ref_recall + EPS:
        return True, "dev.recall improved with stable dev.f1"

    cand_accuracy = float_metric(cand, "accuracy")
    ref_accuracy = float_metric(ref, "accuracy")
    if (
        abs(cand_f1 - ref_f1) <= EPS
        and abs(cand_recall - ref_recall) <= EPS
        and cand_accuracy > ref_accuracy + EPS
    ):
        return True, "dev.accuracy improved with stable dev.f1 and dev.recall"

    return False, "dev split did not improve on f1/recall/accuracy"


def split_non_regression(candidate: Dict[str, Any], reference: Dict[str, Any], split: str) -> Tuple[bool, List[str]]:
    cand = split_score(candidate, split)
    ref = split_score(reference, split)
    failures: List[str] = []
    for metric in ("f1", "recall", "accuracy"):
        if float_metric(cand, metric) + EPS < float_metric(ref, metric):
            failures.append(f"{split}.{metric} regressed")
    return (not failures), failures


def evidence_non_regression(candidate: Dict[str, Any], reference: Dict[str, Any], split: str) -> Tuple[bool, str]:
    cand = split_score(candidate, split)
    ref = split_score(reference, split)
    if float_metric(cand, "evidence_adequacy") + EPS < float_metric(ref, "evidence_adequacy"):
        return False, f"{split}.evidence_adequacy regressed"
    return True, ""


def high_conf_fp_non_regression(candidate: Dict[str, Any], reference: Dict[str, Any], split: str) -> Tuple[bool, str]:
    cand = split_score(candidate, split)
    ref = split_score(reference, split)
    if float_metric(cand, "high_confidence_false_positive_rate") > float_metric(ref, "high_confidence_false_positive_rate") + EPS:
        return False, f"{split}.high_confidence_false_positive_rate regressed"
    return True, ""


def decide_candidate(
    manifest: Dict[str, Any],
    scoreboard: Dict[str, Any],
    candidate_id: str,
    evaluated_splits: List[str] | None = None,
) -> Dict[str, Any]:
    reference = scoreboard.get("best", {})
    current = scoreboard.get("current", {})
    keep_gate = manifest.get("grading", {}).get("keep_gate", {})
    decision_reasons: List[str] = []
    if evaluated_splits is None:
        evaluated_splits = [
            split
            for split in ("dev", "holdout", "cross_repo", "canary")
            if split_case_count(scoreboard, split) > 0
        ]
    evaluated_split_set = set(evaluated_splits)

    if is_baseline(candidate_id):
        return {
            "candidate_id": candidate_id,
            "decision": "keep",
            "decision_reasons": ["baseline established"],
            "evaluated_splits": evaluated_splits,
            "reference_candidate_id": "baseline",
        }

    if keep_gate.get("require_dev_improvement", True):
        ok, reason = dev_improved(current, reference)
        if not ok:
            return {
                "candidate_id": candidate_id,
                "decision": "discard",
                "decision_reasons": [reason],
                "evaluated_splits": evaluated_splits,
                "reference_candidate_id": reference.get("candidate_id", "baseline"),
            }
        decision_reasons.append(reason)

    for split_name, gate_key in (("holdout", "require_holdout_non_regression"), ("cross_repo", "require_cross_repo_non_regression")):
        if not keep_gate.get(gate_key, True):
            continue
        if split_name not in evaluated_split_set or split_case_count(scoreboard, split_name) <= 0:
            continue
        ok, failures = split_non_regression(current, reference, split_name)
        if not ok:
            return {
                "candidate_id": candidate_id,
                "decision": "discard",
                "decision_reasons": failures,
                "evaluated_splits": evaluated_splits,
                "reference_candidate_id": reference.get("candidate_id", "baseline"),
            }
        decision_reasons.append(f"{split_name} non-regression passed")

    if keep_gate.get("require_evidence_non_regression", True):
        for split_name in ("dev", "holdout", "cross_repo"):
            if split_name not in evaluated_split_set or split_case_count(scoreboard, split_name) <= 0:
                continue
            ok, reason = evidence_non_regression(current, reference, split_name)
            if not ok:
                return {
                    "candidate_id": candidate_id,
                    "decision": "discard",
                    "decision_reasons": [reason],
                    "evaluated_splits": evaluated_splits,
                    "reference_candidate_id": reference.get("candidate_id", "baseline"),
                }
        decision_reasons.append("evidence non-regression passed")

    if keep_gate.get("require_high_confidence_fp_non_regression", True):
        for split_name in ("dev", "holdout", "cross_repo"):
            if split_name not in evaluated_split_set or split_case_count(scoreboard, split_name) <= 0:
                continue
            ok, reason = high_conf_fp_non_regression(current, reference, split_name)
            if not ok:
                return {
                    "candidate_id": candidate_id,
                    "decision": "discard",
                    "decision_reasons": [reason],
                    "evaluated_splits": evaluated_splits,
                    "reference_candidate_id": reference.get("candidate_id", "baseline"),
                }
        decision_reasons.append("high-confidence false-positive non-regression passed")

    if "canary" in evaluated_split_set and split_case_count(scoreboard, "canary") > 0:
        decision_reasons.append("canary executed for visibility")

    return {
        "candidate_id": candidate_id,
        "decision": "keep",
        "decision_reasons": decision_reasons,
        "evaluated_splits": evaluated_splits,
        "reference_candidate_id": reference.get("candidate_id", "baseline"),
    }


def update_after_decision(
    run_dir: Path,
    candidate_id: str,
    decision: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    scoreboard_path = run_dir / "scoreboard.json"
    run_state_path = run_dir / "run-state.json"
    scoreboard = read_json(scoreboard_path)
    run_state = read_json(run_state_path)

    current_target_project = candidate_target_project_payload(run_dir, run_state, candidate_id)

    if decision["decision"] == "keep":
        scoreboard["best"] = copy.deepcopy(scoreboard.get("current", {}))
        run_state["best"] = {"candidate_id": candidate_id}
        if isinstance(current_target_project, dict):
            run_state["best"]["target_project"] = current_target_project
        counters = run_state.setdefault("counters", {"keeps": 0, "discards": 0, "crashes": 0})
        counters["keeps"] = int(counters.get("keeps", 0) or 0) + (0 if is_baseline(candidate_id) else 1)
        status = "candidate_kept"
        next_action = "propose next packet"
    else:
        counters = run_state.setdefault("counters", {"keeps": 0, "discards": 0, "crashes": 0})
        counters["discards"] = int(counters.get("discards", 0) or 0) + 1
        status = "candidate_discarded"
        next_action = "inspect failures and propose next packet"

    run_state["current"] = {"candidate_id": candidate_id}
    if isinstance(current_target_project, dict):
        run_state["current"]["target_project"] = current_target_project
    run_state.setdefault("supervisor", {})
    run_state["supervisor"]["status"] = status
    run_state["supervisor"]["next_action"] = next_action
    run_state["supervisor"]["last_candidate_decision"] = decision["decision"]
    run_state["supervisor"]["last_candidate_id"] = candidate_id
    run_state["supervisor"]["decision_reasons"] = decision["decision_reasons"]

    write_json(scoreboard_path, scoreboard)
    write_json(run_state_path, run_state)
    return scoreboard, run_state


def run_split(
    manifest_path: Path,
    run_dir: Path,
    candidate_id: str,
    split: str,
    limit: int | None,
) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(default_run_packet_script()),
        "--manifest",
        str(manifest_path),
        "--run-dir",
        str(run_dir),
        "--split",
        split,
        "--candidate-id",
        candidate_id,
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])
    result = run_subprocess(command, Path.cwd())
    if result.returncode != 0:
        raise RuntimeError(
            f"run_packet failed for split {split}:\n"
            f"command={' '.join(command)}\n"
            f"stderr={result.stderr}"
        )
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"run_packet did not emit valid JSON summary for split {split}:\nstdout={result.stdout}"
        ) from exc
    return payload


def select_splits(strategy: str) -> List[str]:
    if strategy == "full":
        return ["dev", "holdout", "cross_repo", "canary"]
    return ["dev"]


def maybe_extend_staged_splits(
    strategy: str,
    scoreboard: Dict[str, Any],
    manifest: Dict[str, Any],
    candidate_id: str,
    executed_splits: List[str],
) -> List[str]:
    if strategy != "staged":
        return []
    decision = decide_candidate(manifest, scoreboard, candidate_id, executed_splits)
    if decision["decision"] != "keep":
        return []
    return ["holdout", "cross_repo", "canary"]


def write_decision_artifact(run_dir: Path, decision: Dict[str, Any]) -> Path:
    decisions_dir = run_dir / "decisions"
    path = decisions_dir / f"{decision['candidate_id']}.decision.json"
    write_json(path, decision)
    append_jsonl(run_dir / "candidate-ledger.jsonl", {"event": "decision", **decision})
    return path


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    run_dir = Path(args.run_dir).resolve()

    strategy = (
        args.strategy
        or manifest.get("execution", {}).get("candidate_evaluation", {}).get("strategy")
        or "staged"
    )

    scoreboard_path = run_dir / "scoreboard.json"
    run_state_path = run_dir / "run-state.json"
    scoreboard = read_json(scoreboard_path)
    run_state = read_json(run_state_path)

    prepare_current_candidate(scoreboard, args.candidate_id)
    set_run_state_current(run_state, args.candidate_id, strategy, run_dir)
    write_json(scoreboard_path, scoreboard)
    write_json(run_state_path, run_state)

    limits = {
        "dev": args.limit_dev,
        "holdout": args.limit_holdout,
        "cross_repo": args.limit_cross_repo,
        "canary": args.limit_canary,
    }

    executed_splits: List[str] = []
    split_runs: List[Dict[str, Any]] = []
    for split in select_splits(strategy):
        if split_case_count(scoreboard, split) <= 0:
            continue
        split_runs.append(run_split(manifest_path, run_dir, args.candidate_id, split, limits.get(split)))
        executed_splits.append(split)

    scoreboard = read_json(scoreboard_path)
    trailing_splits = maybe_extend_staged_splits(strategy, scoreboard, manifest, args.candidate_id, executed_splits)
    for split in trailing_splits:
        if split_case_count(scoreboard, split) <= 0:
            continue
        split_runs.append(run_split(manifest_path, run_dir, args.candidate_id, split, limits.get(split)))
        executed_splits.append(split)

    scoreboard = read_json(scoreboard_path)
    decision = decide_candidate(manifest, scoreboard, args.candidate_id, executed_splits)
    decision["strategy"] = strategy
    decision["evaluated_splits"] = executed_splits
    decision["executed_splits"] = executed_splits
    decision["target_project_revision"] = target_project_revision(manifest, run_dir)
    decision["split_runs"] = split_runs

    update_after_decision(run_dir, args.candidate_id, decision)
    decision_path = write_decision_artifact(run_dir, decision)

    print(
        json.dumps(
            {
                "candidate_id": args.candidate_id,
                "decision": decision["decision"],
                "executed_splits": executed_splits,
                "decision_path": str(decision_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
