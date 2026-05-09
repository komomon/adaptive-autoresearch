#!/usr/bin/env python3
"""
Build a compact review queue for sparse normalized cases that still need LLM review.

This script does not call a model directly.
It prepares the minimal queue and prompt-friendly packets so a later adapter or
runner can process only the rows that require structure completion.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

from _shared import read_jsonl, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract sparse cases that require LLM-assisted normalization."
    )
    parser.add_argument("--input", required=True, help="Normalized input jsonl path.")
    parser.add_argument("--output", required=True, help="Review queue jsonl path.")
    parser.add_argument(
        "--prompt-output",
        help="Optional markdown path for a reusable review prompt.",
    )
    return parser.parse_args()


def build_review_packet(case: Dict[str, Any]) -> Dict[str, Any]:
    normalization = case.get("normalization", {})
    return {
        "case_id": case.get("case_id"),
        "source_row": normalization.get("source_row"),
        "missing_fields": normalization.get("missing_fields", []),
        "inferred_fields": normalization.get("inferred_fields", []),
        "allowed_actions": [
            "normalize field names",
            "fill structural defaults",
            "extract obvious metadata from notes",
        ],
        "forbidden_actions": [
            "invent vulnerability labels",
            "invent verdicts",
            "invent vuln locations",
            "rewrite ground truth",
        ],
        "case": case,
    }


def build_prompt_markdown() -> str:
    return """# LLM-Assisted Sparse Case Review

## Goal

You are reviewing sparse benchmark rows before they enter the formal grading loop.

## Allowed

- Normalize structure
- Map obvious synonyms into the shared schema
- Fill safe defaults for transport/language when they are clearly absent
- Extract obvious metadata from notes or existing fields

## Forbidden

- Do not invent whether a vulnerability exists
- Do not invent vulnerability types
- Do not invent function names or line numbers
- Do not rewrite ground truth labels

## Output Requirements

Return only a corrected normalized case object plus a short explanation of:

1. which fields were normalized
2. which fields remain unknown
3. why those unknown fields could not be safely inferred
"""


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    queue: List[Dict[str, Any]] = []

    for case in read_jsonl(input_path):
        normalization = case.get("normalization", {})
        if normalization.get("needs_llm_review"):
            queue.append(build_review_packet(case))

    write_jsonl(output_path, queue)

    if args.prompt_output:
        prompt_path = Path(args.prompt_output).resolve()
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(build_prompt_markdown(), encoding="utf-8")

    print(f"Wrote {len(queue)} review packets to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
