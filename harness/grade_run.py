#!/usr/bin/env python3
"""
Grade canonicalized TargetAuditResult JSONL against NormalizedCase JSONL.

This is a minimal grader skeleton:
- computes accuracy / precision / recall / f1
- estimates evidence adequacy
- emits a scoreboard fragment and per-case grading results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _shared import read_jsonl, write_json, write_jsonl


AUTHZ_COMPAT = {
    "broken-access-control": {
        "broken-access-control",
        "idor",
        "bola",
        "bfla",
        "unauthorized",
        "identity-impersonation",
        "cross-tenant",
        "authz"
    },
    "authz": {
        "broken-access-control",
        "idor",
        "bola",
        "bfla",
        "unauthorized",
        "identity-impersonation",
        "cross-tenant",
        "authz"
    }
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade a target project run.")
    parser.add_argument("--cases", required=True, help="Normalized cases jsonl.")
    parser.add_argument("--results", required=True, help="Target audit results jsonl.")
    parser.add_argument("--output", required=True, help="Per-case grading jsonl output.")
    parser.add_argument("--scoreboard-output", required=True, help="Aggregate scoreboard json output.")
    parser.add_argument("--split", required=True, help="Split name, e.g. dev/holdout/cross_repo/canary.")
    return parser.parse_args()


def expected_type_set(expected: Dict[str, Any]) -> set[str]:
    value = expected.get("vulnerability_type")
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    text = str(value).strip().lower()
    return {text} if text else set()


def result_type_set(result: Dict[str, Any]) -> set[str]:
    verdict = result.get("verdict", {})
    value = verdict.get("vulnerability_type")
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    text = str(value).strip().lower()
    return {text} if text else set()


def types_match(expected: set[str], actual: set[str]) -> bool:
    if not expected:
        return True
    if expected & actual:
        return True
    for item in expected:
        compat = AUTHZ_COMPAT.get(item, {item})
        if compat & actual:
            return True
    return False


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "有"}


def normalize_expected_locations(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [line.strip().lower() for line in text.splitlines() if line.strip()]


def evidence_adequacy(expected_locations: List[str], result: Dict[str, Any]) -> float:
    evidence = result.get("evidence", {})
    actual_locations = [str(item).strip().lower() for item in evidence.get("locations", [])]
    actual_functions = [str(item).strip().lower() for item in evidence.get("functions", [])]
    if not expected_locations:
        return 1.0 if (actual_locations or actual_functions) else 0.5
    haystack = actual_locations + actual_functions
    if not haystack:
        return 0.0
    for expected in expected_locations:
        if any(expected in item or item in expected for item in haystack):
            return 1.0
    return 0.0


def chain_completeness(result: Dict[str, Any]) -> float:
    artifacts = result.get("artifacts", {})
    score = 0
    for key in ("path_pack", "context_pack", "guard_pack", "evidence_pack"):
        if key in artifacts and artifacts.get(key):
            score += 1
    return score / 4.0


def precision_recall_f1(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def main() -> int:
    args = parse_args()
    cases = {row["case_id"]: row for row in read_jsonl(Path(args.cases).resolve())}
    results = {row["case_id"]: row for row in read_jsonl(Path(args.results).resolve())}

    per_case_rows: List[Dict[str, Any]] = []
    tp = fp = tn = fn = 0
    evidence_scores: List[float] = []
    chain_scores: List[float] = []
    high_conf_fp_count = 0
    high_conf_total = 0

    for case_id, case in cases.items():
        expected = case.get("expected", {})
        expected_has_vuln = as_bool(expected.get("has_vulnerability"))
        expected_types = expected_type_set(expected)
        expected_locations = normalize_expected_locations(expected.get("vuln_function_or_line"))

        result = results.get(case_id)
        missing_result = result is None
        if result is None:
            result = {
                "case_id": case_id,
                "entry": {"name": case.get("entry", {}).get("name", "")},
                "verdict": {
                    "has_vulnerability": False,
                    "status": "unknown",
                    "confidence": 0.0
                },
                "evidence": {
                    "files": [],
                    "functions": [],
                    "locations": [],
                    "reasoning_mode": "report-derived"
                }
            }

        verdict = result.get("verdict", {})
        actual_has_vuln = as_bool(verdict.get("has_vulnerability"))
        actual_types = result_type_set(result)
        verdict_match = (expected_has_vuln == actual_has_vuln) and (not missing_result)
        type_match = types_match(expected_types, actual_types) and (not missing_result)
        evidence_score = evidence_adequacy(expected_locations, result)
        chain_score = chain_completeness(result)
        confidence = float(verdict.get("confidence", 0.0) or 0.0)

        if missing_result:
            if expected_has_vuln:
                fn += 1
            else:
                fp += 1
        elif expected_has_vuln and actual_has_vuln:
            tp += 1
        elif not expected_has_vuln and actual_has_vuln:
            fp += 1
        elif expected_has_vuln and not actual_has_vuln:
            fn += 1
        else:
            tn += 1

        if confidence >= 0.8:
            high_conf_total += 1
            if not verdict_match:
                high_conf_fp_count += 1

        evidence_scores.append(evidence_score)
        chain_scores.append(chain_score)
        per_case_rows.append(
            {
                "case_id": case_id,
                "split": args.split,
                "verdict_match": verdict_match,
                "type_match": type_match,
                "evidence_adequacy": evidence_score,
                "chain_completeness": chain_score,
                "expected_has_vulnerability": expected_has_vuln,
                "actual_has_vulnerability": actual_has_vuln,
                "confidence": confidence,
                "missing_result": missing_result,
            }
        )

    accuracy = (tp + tn) / len(cases) if cases else 0.0
    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    scoreboard = {
      "split": args.split,
      "accuracy": accuracy,
      "precision": precision,
      "recall": recall,
      "f1": f1,
      "evidence_adequacy": sum(evidence_scores) / len(evidence_scores) if evidence_scores else 0.0,
      "chain_completeness": sum(chain_scores) / len(chain_scores) if chain_scores else 0.0,
      "high_confidence_false_positive_rate": (
          high_conf_fp_count / high_conf_total if high_conf_total else 0.0
      ),
      "case_count": len(cases),
      "tp": tp,
      "fp": fp,
      "tn": tn,
      "fn": fn
    }

    write_jsonl(Path(args.output).resolve(), per_case_rows)
    write_json(Path(args.scoreboard_output).resolve(), scoreboard)
    print(json.dumps(scoreboard, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
