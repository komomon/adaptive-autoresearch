#!/usr/bin/env python3
"""
Prepare one candidate workspace from baseline/best/current.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from _shared import load_manifest
from version_backend import prepare_candidate_workspace


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one candidate workspace.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Initialized run directory.")
    parser.add_argument("--candidate-id", required=True, help="Candidate id to prepare.")
    parser.add_argument(
        "--source",
        default="best",
        help="Source candidate reference: best/baseline/current/or a concrete candidate id.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest: Dict[str, Any] = load_manifest(Path(args.manifest).resolve())
    run_dir = Path(args.run_dir).resolve()
    metadata = prepare_candidate_workspace(
        manifest=manifest,
        run_dir=run_dir,
        candidate_id=args.candidate_id,
        source_reference=args.source,
    )
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
