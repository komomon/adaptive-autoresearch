#!/usr/bin/env python3
"""
Propose one methodology-first packet from failing cases.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from model_backends import claude_agent_sdk_query
from run_experiment import load_manifest
from version_backend import candidate_workspace_dir, read_json, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Propose one optimization packet.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", required=True, help="Source candidate id to inspect.")
    parser.add_argument("--split", default="dev", help="Split to inspect, defaults to dev.")
    parser.add_argument("--packet-id", required=True, help="Packet id to write.")
    return parser.parse_args()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def parse_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    candidates.extend(fenced)
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(stripped[first_brace : last_brace + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise SystemExit(f"Packet proposer did not return valid JSON. Raw response:\n{stripped[:4000]}")


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
            or float(row.get("evidence_adequacy", 0.0) or 0.0) < 1.0
            or float(row.get("chain_completeness", 0.0) or 0.0) < 1.0
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


def default_proposal_config(manifest: Dict[str, Any]) -> Dict[str, Any]:
    explicit = manifest.get("optimization", {}).get("proposal")
    if isinstance(explicit, dict):
        return explicit
    invocation = manifest.get("experiment", {}).get("target_project", {}).get("invocation", {})
    if isinstance(invocation, dict) and invocation.get("mode") == "claude-agent-sdk-python":
        cfg = dict(invocation)
        cfg.setdefault("permission_mode", "default")
        cfg.setdefault("max_turns", 8)
        cfg.setdefault("timeout_seconds", 120)
        return cfg
    return {
        "mode": "claude-agent-sdk-python",
        "permission_mode": "default",
        "max_turns": 8,
        "timeout_seconds": 120,
    }


def render_prompt(
    packet_id: str,
    candidate_id: str,
    failures: List[Dict[str, Any]],
    editable_files: List[str],
    optimization_policy: Dict[str, Any],
) -> str:
    return f"""You are proposing exactly one methodology-first optimization packet for a target vulnerability-audit project.

Hard constraints:
1. Propose exactly one primary methodology change.
2. Minimum necessary change only. No broad rewrites.
3. Do not solve the benchmark by memorizing case patterns.
4. Do not add vulnerability keyword rules or field-name shortcuts.
5. Prefer changes to skill instructions, methodology docs, dispatch strategy, evidence schema, or verifier behavior.
6. Output exactly one JSON object.

Optimization policy:
{json.dumps(optimization_policy, ensure_ascii=False, indent=2)}

Editable files:
{json.dumps(editable_files, ensure_ascii=False, indent=2)}

Failed cases:
{json.dumps(failures, ensure_ascii=False, indent=2)}

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
    prompt = render_prompt(args.packet_id, args.candidate_id, failures, editable_files, optimization_policy)

    print(
        f"  [propose] {len(failures)} failures, {len(editable_files)} editable files → proposing packet {args.packet_id} ...",
        file=sys.stderr, flush=True,
    )

    proposal_cfg = default_proposal_config(manifest)
    raw_text = claude_agent_sdk_query(prompt, workspace, proposal_cfg, heartbeat_label=f"propose {args.packet_id}")

    payload = parse_json_object(raw_text)
    payload.setdefault("packet_id", args.packet_id)
    payload.setdefault("source_candidate_id", args.candidate_id)
    payload.setdefault("target_files", [])
    payload.setdefault("edit_instructions", [])
    payload.setdefault("validation_expectation", {"should_improve": [], "must_not_regress": []})
    payload["failure_case_ids"] = [item["case_id"] for item in failures]

    packet_dir = run_dir / "packets" / args.packet_id
    write_json(packet_dir / "packet.json", payload)
    write_json(
        packet_dir / "proposal-context.json",
        {
            "candidate_id": args.candidate_id,
            "split": args.split,
            "failure_count": len(failures),
            "editable_file_count": len(editable_files),
        },
    )
    (packet_dir / "proposal.raw.txt").write_text(raw_text, encoding="utf-8")
    print(f"  [propose] Packet {args.packet_id} written.", file=sys.stderr, flush=True)
    print(json.dumps({"packet_id": args.packet_id, "packet_path": str(packet_dir / "packet.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
