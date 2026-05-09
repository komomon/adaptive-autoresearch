#!/usr/bin/env python3
"""
Canonicalize a target project's rich raw output into TargetAuditResult.

This script is intentionally separate from the target project itself:
- the target project can keep rich, domain-specific output
- autoresearch only extracts the minimum evaluation-facing fields it needs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from _shared import ensure_target_result_shape, parse_json_object, read_json
from model_backends import claude_agent_sdk_query


DEFAULT_PROMPT = """You are aligning a target audit project's rich raw output to a strict evaluation-facing JSON object.

Important constraints:
1. The target project's raw output may contain more detail than the evaluation schema.
2. Keep only evaluation-facing information in the final JSON, but do not invent anything.
3. Do not invent vulnerability labels, evidence, locations, functions, or confidence.
4. If the raw output is uncertain, preserve that uncertainty.
5. Output exactly one JSON object.

Required JSON shape:
{{
  "case_id": "...",
  "entry": {{
    "name": "...",
    "transport": "...",
    "language": "..."
  }},
  "verdict": {{
    "has_vulnerability": true,
    "vulnerability_type": ["..."],
    "confidence": 0.0,
    "status": "confirmed|rejected|unknown|insufficient-evidence",
    "summary": "..."
  }},
  "evidence": {{
    "files": ["..."],
    "functions": ["..."],
    "locations": ["..."],
    "reasoning_mode": "code-grounded|mixed|report-derived",
    "notes": ["..."]
  }},
  "artifacts": {{
    "entry_pack": {{}},
    "path_pack": {{}},
    "context_pack": {{}},
    "guard_pack": {{}},
    "evidence_pack": {{}}
  }},
  "raw_output_ref": "..."
}}

Case metadata:
{case_json}

Raw output:
{raw_output}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonicalize raw target output into TargetAuditResult.")
    parser.add_argument("--case-file", required=True, help="Path to one normalized case JSON file.")
    parser.add_argument("--cwd", required=True, help="Working directory for canonicalization.")
    parser.add_argument("--output", help="Write canonicalized JSON here. Defaults to stdout.")
    parser.add_argument("--raw-file", help="Path to raw output file.")
    parser.add_argument("--raw-text", help="Inline raw output text.")
    parser.add_argument("--raw-output-ref", help="Value for TargetAuditResult.raw_output_ref.")
    parser.add_argument(
        "--mode",
        default="claude-agent-sdk-python",
        choices=["claude-agent-sdk-python"],
        help="Canonicalization backend.",
    )
    parser.add_argument("--prompt-file", help="Optional custom prompt file.")
    parser.add_argument(
        "--allowed-tool",
        action="append",
        default=[],
        help="Allowed tool for SDK invocation. Repeatable.",
    )
    parser.add_argument("--permission-mode", help="Permission mode for SDK invocation.")
    parser.add_argument("--max-turns", type=int, help="Optional SDK max_turns override.")
    parser.add_argument("--timeout-seconds", type=float, help="Optional backend timeout.")
    return parser.parse_args()


def render_prompt(template: str, case: Dict[str, Any], raw_output: str) -> str:
    return template.format(
        case_json=json.dumps(case, ensure_ascii=False, indent=2),
        raw_output=raw_output,
    )


def main() -> int:
    args = parse_args()
    if not args.raw_file and not args.raw_text:
        raise SystemExit("One of --raw-file or --raw-text is required.")

    case = read_json(Path(args.case_file).resolve())
    if args.raw_file:
        raw_file = Path(args.raw_file).resolve()
        raw_output = raw_file.read_text(encoding="utf-8")
        raw_output_ref = args.raw_output_ref or str(raw_file)
    else:
        raw_output = args.raw_text or ""
        raw_output_ref = args.raw_output_ref or "<inline>"

    prompt_template = (
        Path(args.prompt_file).resolve().read_text(encoding="utf-8")
        if args.prompt_file
        else DEFAULT_PROMPT
    )
    prompt = render_prompt(prompt_template, case, raw_output)
    cwd = Path(args.cwd).resolve()

    result_text = claude_agent_sdk_query(
        prompt,
        cwd,
        {
            "allowed_tools": args.allowed_tool,
            "permission_mode": args.permission_mode,
            "max_turns": args.max_turns,
            "timeout_seconds": args.timeout_seconds,
            "model_env": "ANTHROPIC_MODEL",
            "base_url_env": "ANTHROPIC_BASE_URL",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
    )

    payload = parse_json_object(result_text, "Canonicalizer")
    payload = ensure_target_result_shape(case, payload, raw_output_ref)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
