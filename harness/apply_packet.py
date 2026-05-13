#!/usr/bin/env python3
"""
Apply one methodology packet to a prepared candidate workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from _shared import load_manifest, read_json, write_json
from model_backends import claude_agent_sdk_query
from version_backend import candidate_workspace_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply one packet to a candidate workspace.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", required=True, help="Candidate id to modify.")
    parser.add_argument("--packet-file", required=True, help="Packet json path.")
    return parser.parse_args()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_file_digests(workspace: Path, target_files: List[str]) -> Dict[str, str]:
    digests: Dict[str, str] = {}
    for relative in target_files:
        path = (workspace / relative).resolve()
        if path.exists() and path.is_file():
            digests[relative] = file_digest(path)
    return digests


def collect_all_file_digests(workspace: Path) -> Dict[str, str]:
    digests: Dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            digests[rel] = file_digest(path)
    return digests


def modified_files(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    paths = sorted(set(before) | set(after))
    return [path for path in paths if before.get(path) != after.get(path)]


def _optimization_model_base(manifest: Dict[str, Any]) -> Dict[str, Any]:
    base = manifest.get("optimization", {}).get("model")
    return dict(base) if isinstance(base, dict) else {}


def default_apply_config(manifest: Dict[str, Any]) -> Dict[str, Any]:
    invocation = manifest.get("experiment", {}).get("target_project", {}).get("invocation", {})
    opt_base = _optimization_model_base(manifest)
    explicit = manifest.get("optimization", {}).get("apply")
    if isinstance(explicit, dict):
        cfg = {**invocation, **opt_base, **explicit}
    elif opt_base:
        cfg = {**invocation, **opt_base}
    else:
        cfg = dict(invocation)
    cfg["mode"] = "claude-agent-sdk-python"
    cfg.setdefault("permission_mode", "acceptEdits")
    cfg.setdefault("max_turns", 18)
    cfg.setdefault("timeout_seconds", 3600)
    cfg.setdefault("max_timeout_extensions", 1)
    cfg.setdefault("allowed_tools", ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write"])
    return cfg


def render_prompt(packet: Dict[str, Any]) -> str:
    target_files = packet.get("target_files", [])
    has_targets = bool(target_files and any(item.get("path") for item in target_files))
    file_constraint = (
        "Edit only the files listed in target_files unless a tiny adjacent change is strictly required for consistency."
        if has_targets
        else "You may edit any file in the target project. Focus on the changes described in edit_instructions."
    )
    return f"""You are applying exactly one methodology-first optimization packet to the target audit project.

You have full file access to the target project directory. Use Read/Glob/Grep to understand the codebase before making edits.

Hard constraints:
1. Follow the packet exactly.
2. Make only the minimum necessary edits.
3. {file_constraint}
4. Do not add benchmark-specific keyword rules, field-name shortcuts, or dataset memorization.
5. Preserve the target project's existing style unless the packet explicitly says otherwise.
6. After finishing, output a short JSON object summarizing the work.

Packet:
{json.dumps(packet, ensure_ascii=False, indent=2)}

Return JSON in this shape:
{{
  "packet_id": "{packet.get('packet_id', '')}",
  "status": "applied",
  "summary": "...",
  "modified_files": ["..."]
}}
"""


def main() -> int:
    args = parse_args()
    manifest = load_manifest(Path(args.manifest).resolve())
    packet = read_json(Path(args.packet_file).resolve())
    run_dir = Path(args.run_dir).resolve()
    workspace = candidate_workspace_dir(run_dir, args.candidate_id)
    if not workspace.exists():
        raise SystemExit(f"Candidate workspace does not exist: {workspace}")

    target_files = [str(item.get("path")) for item in packet.get("target_files", []) if item.get("path")]
    before = collect_all_file_digests(workspace)
    apply_cfg = default_apply_config(manifest)
    prompt = render_prompt(packet)

    if apply_cfg.get("mode") != "claude-agent-sdk-python":
        raise SystemExit("Packet apply currently requires claude-agent-sdk-python mode.")

    raw_text = claude_agent_sdk_query(
        prompt, workspace, apply_cfg,
        heartbeat_label=f"apply {packet.get('packet_id', 'unknown')}",
    )

    after = collect_all_file_digests(workspace)
    changed = modified_files(before, after)
    packet_dir = Path(args.packet_file).resolve().parent
    write_json(
        packet_dir / "apply-result.json",
        {
            "packet_id": packet.get("packet_id"),
            "candidate_id": args.candidate_id,
            "status": "applied",
            "modified_files": changed,
            "target_files": target_files,
        },
    )
    (packet_dir / "apply.raw.txt").write_text(raw_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "packet_id": packet.get("packet_id"),
                "candidate_id": args.candidate_id,
                "modified_files": changed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
