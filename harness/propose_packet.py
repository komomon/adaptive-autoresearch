#!/usr/bin/env python3
"""
Propose one methodology-first packet from failing cases.

Uses a two-phase approach:
  Phase A: analyze failures in small batches (2 per batch)
  Phase B: synthesize all batch observations into one proposal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from model_backends import claude_agent_sdk_query
from _shared import load_manifest, parse_json_object, read_jsonl, write_json
from version_backend import candidate_workspace_dir

BATCH_SIZE = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Propose one optimization packet.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", required=True, help="Source candidate id to inspect.")
    parser.add_argument("--split", default="dev", help="Split to inspect, defaults to dev.")
    parser.add_argument("--packet-id", required=True, help="Packet id to write.")
    return parser.parse_args()


def list_editable_files(workspace: Path, editable_scope: List[str]) -> List[str]:
    collected: List[str] = []
    for scope in editable_scope:
        scope_path = (workspace / scope).resolve()
        if scope_path.is_file():
            collected.append(str(scope_path.relative_to(workspace)).replace("\\", "/"))
            continue
        if scope_path.is_dir():
            for path in sorted(scope_path.rglob("*")):
                if path.is_file():
                    collected.append(str(path.relative_to(workspace)).replace("\\", "/"))
    return collected[:80]


def build_failure_bundle(run_dir: Path, candidate_id: str, split: str) -> List[Dict[str, Any]]:
    grading_rows = read_jsonl(run_dir / "grading" / candidate_id / f"{split}.grading.jsonl")
    case_rows = {row["case_id"]: row for row in read_jsonl(run_dir / "splits" / f"{split}.jsonl")}
    result_rows = {
        row["case_id"]: row
        for row in read_jsonl(run_dir / "target-results" / candidate_id / f"{split}.results.jsonl")
    }
    failures: List[Dict[str, Any]] = []
    for row in grading_rows:
        needs_optimization = (
            not bool(row.get("verdict_match", False))
            or not bool(row.get("type_match", True))
            or float(row.get("evidence_adequacy", 0.0) or 0.0) < 0.5
            or float(row.get("chain_completeness", 0.0) or 0.0) < 0.25
        )
        if not needs_optimization:
            continue
        case = case_rows.get(row["case_id"], {})
        result = result_rows.get(row["case_id"], {})
        failures.append(
            {
                "case_id": row.get("case_id"),
                "verdict_match": row.get("verdict_match"),
                "type_match": row.get("type_match"),
                "expected_has_vulnerability": row.get("expected_has_vulnerability"),
                "actual_has_vulnerability": row.get("actual_has_vulnerability"),
                "confidence": row.get("confidence"),
                "evidence_adequacy": row.get("evidence_adequacy"),
                "chain_completeness": row.get("chain_completeness"),
                "missing_result": row.get("missing_result"),
                "entry": case.get("entry", {}),
                "notes": case.get("notes"),
                "expected": case.get("expected", {}),
                "summary": result.get("verdict", {}).get("summary", ""),
                "result_notes": result.get("evidence", {}).get("notes", []),
            }
        )
    return failures


def _optimization_model_base(manifest: Dict[str, Any]) -> Dict[str, Any]:
    base = manifest.get("optimization", {}).get("model")
    return dict(base) if isinstance(base, dict) else {}


def default_proposal_config(manifest: Dict[str, Any]) -> Dict[str, Any]:
    invocation = manifest.get("experiment", {}).get("target_project", {}).get("invocation", {})
    opt_base = _optimization_model_base(manifest)
    explicit = manifest.get("optimization", {}).get("proposal")
    if isinstance(explicit, dict):
        cfg = {**invocation, **opt_base, **explicit}
    elif opt_base:
        cfg = {**invocation, **opt_base}
    elif isinstance(invocation, dict) and invocation.get("mode") == "claude-agent-sdk-python":
        cfg = dict(invocation)
    else:
        cfg = {}
    cfg.setdefault("mode", "claude-agent-sdk-python")
    cfg.setdefault("permission_mode", "default")
    cfg.setdefault("max_turns", 8)
    cfg.setdefault("timeout_seconds", 3600)
    cfg.setdefault("max_timeout_extensions", 1)
    return cfg


def render_batch_analysis_prompt(
    batch_failures: List[Dict[str, Any]],
    batch_index: int,
    total_batches: int,
) -> str:
    return f"""You are analyzing a small batch of {len(batch_failures)} failing case(s) from a vulnerability-audit project.
This is batch {batch_index + 1} of {total_batches}. Focus only on these cases.

For each case, identify:
- What went wrong (verdict mismatch, missing evidence, etc.)
- The suspected root cause pattern
- Whether this looks like a systematic methodology gap

Failed cases in this batch:
{json.dumps(batch_failures, ensure_ascii=False, indent=2)}

Return a JSON object with this shape:
{{
  "observations": ["observation 1", "observation 2"],
  "common_patterns": ["pattern shared across cases in this batch"],
  "suspected_root_cause": "one-sentence root cause hypothesis"
}}
"""


def render_synthesis_prompt(
    packet_id: str,
    candidate_id: str,
    batch_observations: List[Dict[str, Any]],
    editable_files: List[str],
    optimization_policy: Dict[str, Any],
    all_failure_case_ids: List[str],
) -> str:
    return f"""You are proposing exactly one methodology-first optimization packet for a target vulnerability-audit project.

You have already analyzed all failing cases in small batches. Below are the accumulated observations from {len(batch_observations)} batch analyses covering {len(all_failure_case_ids)} total failures.

Batch observations:
{json.dumps(batch_observations, ensure_ascii=False, indent=2)}

Hard constraints:
1. Propose exactly one primary methodology change based on the observations above.
2. Minimum necessary change only. No broad rewrites.
3. Do not solve the benchmark by memorizing case patterns.
4. Do not add vulnerability keyword rules or field-name shortcuts.
5. Prefer changes to skill instructions, methodology docs, dispatch strategy, evidence schema, or verifier behavior.
6. Output exactly one JSON object.

Optimization policy:
{json.dumps(optimization_policy, ensure_ascii=False, indent=2)}

Editable files:
{json.dumps(editable_files, ensure_ascii=False, indent=2)}

All failed case IDs: {json.dumps(all_failure_case_ids, ensure_ascii=False)}

Return JSON in this shape:
{{
  "packet_id": "{packet_id}",
  "source_candidate_id": "{candidate_id}",
  "primary_axis": "...",
  "summary": "...",
  "failure_hypothesis": "...",
  "why_this_should_generalize": "...",
  "target_files": [
    {{
      "path": "...",
      "reason": "..."
    }}
  ],
  "edit_instructions": [
    {{
      "file": "...",
      "instruction": "..."
    }}
  ],
  "validation_expectation": {{
    "should_improve": ["..."],
    "must_not_regress": ["..."]
  }}
}}
"""


def main() -> int:
    args = parse_args()
    manifest = load_manifest(Path(args.manifest).resolve())
    run_dir = Path(args.run_dir).resolve()
    workspace = candidate_workspace_dir(run_dir, args.candidate_id)
    if not workspace.exists():
        workspace = Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve()

    failures = build_failure_bundle(run_dir, args.candidate_id, args.split)
    if not failures:
        raise SystemExit(f"No failing cases found for candidate {args.candidate_id} split {args.split}.")

    editable_scope = list(manifest.get("experiment", {}).get("target_project", {}).get("editable_scope", []))
    editable_files = list_editable_files(workspace, editable_scope)
    optimization_policy = manifest.get("experiment", {}).get("target_project", {}).get("optimization_policy", {})
    proposal_cfg = default_proposal_config(manifest)

    # Phase A: batch analysis
    batches = [failures[i:i + BATCH_SIZE] for i in range(0, len(failures), BATCH_SIZE)]
    batch_observations: List[Dict[str, Any]] = []

    print(
        f"  [propose] {len(failures)} failures → {len(batches)} batches of ≤{BATCH_SIZE}",
        file=sys.stderr, flush=True,
    )

    for bi, batch in enumerate(batches):
        label = f"propose batch {bi + 1}/{len(batches)}"
        print(f"  [propose] {label} (cases: {', '.join(f.get('case_id', '?') for f in batch)}) ...", file=sys.stderr, flush=True)
        batch_prompt = render_batch_analysis_prompt(batch, bi, len(batches))
        try:
            raw_batch = claude_agent_sdk_query(batch_prompt, workspace, proposal_cfg, heartbeat_label=label)
            obs = parse_json_object(raw_batch, f"Batch analysis {bi + 1}")
            obs["batch_index"] = bi
            batch_observations.append(obs)
        except Exception as exc:
            print(f"  [propose] WARNING: batch {bi + 1} failed ({exc}), skipping", file=sys.stderr, flush=True)

    if not batch_observations:
        raise RuntimeError("All batch analyses failed. Cannot synthesize proposal.")

    # Phase B: synthesis
    all_failure_ids = [f["case_id"] for f in failures]
    synth_label = f"propose synthesis ({len(batch_observations)} batches)"
    print(f"  [propose] {synth_label} ...", file=sys.stderr, flush=True)

    synthesis_prompt = render_synthesis_prompt(
        args.packet_id,
        args.candidate_id,
        batch_observations,
        editable_files,
        optimization_policy,
        all_failure_ids,
    )
    raw_text = claude_agent_sdk_query(synthesis_prompt, workspace, proposal_cfg, heartbeat_label=synth_label)

    payload = parse_json_object(raw_text, "Packet proposer")
    payload.setdefault("packet_id", args.packet_id)
    payload.setdefault("source_candidate_id", args.candidate_id)
    payload.setdefault("target_files", [])
    payload.setdefault("edit_instructions", [])
    payload.setdefault("validation_expectation", {"should_improve": [], "must_not_regress": []})
    payload["failure_case_ids"] = all_failure_ids

    packet_dir = run_dir / "packets" / args.packet_id
    write_json(packet_dir / "packet.json", payload)
    write_json(
        packet_dir / "proposal-context.json",
        {
            "candidate_id": args.candidate_id,
            "split": args.split,
            "failure_count": len(failures),
            "editable_file_count": len(editable_files),
            "batch_count": len(batches),
            "batch_success_count": len(batch_observations),
        },
    )
    (packet_dir / "proposal.raw.txt").write_text(raw_text, encoding="utf-8")
    print(json.dumps({"packet_id": args.packet_id, "packet_path": str(packet_dir / "packet.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
