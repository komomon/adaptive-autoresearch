#!/usr/bin/env python3
"""
Run a single normalized case through the configured target project invocation path.

This validates:
- target model backend configuration
- target project invocation
- raw output capture
- optional canonicalization to TargetAuditResult
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _shared import load_manifest, read_json, write_json
from run_packet import invoke_target_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test one target project case.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--case-file", required=True, help="One normalized case JSON file.")
    parser.add_argument("--output-dir", required=True, help="Smoke output directory.")
    parser.add_argument("--run-id", default="smoke-run", help="Run id label used in prompts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(Path(args.manifest).resolve())
    case = read_json(Path(args.case_file).resolve())
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    target_project = manifest.get("experiment", {}).get("target_project", {})
    invocation = target_project.get("invocation", {})
    result, backend_used = invoke_target_project(invocation, case, manifest, args.run_id, output_dir, "smoke")

    final_path = output_dir / "smoke-target-audit-result.json"
    write_json(final_path, result)
    print(
        json.dumps(
            {
                "case_id": case.get("case_id"),
                "mode": invocation.get("mode", "cli-json"),
                "backend_used": backend_used,
                "output_dir": str(output_dir),
                "target_audit_result": str(final_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
