#!/usr/bin/env python3
"""
Run one packet over a split of cases and collect canonicalized TargetAuditResult rows.

Supported target invocation modes:
- cli-json
- claude-agent-sdk-python

The primary Python path is designed for target projects that are themselves
skill / agent-team projects. It invokes Claude Agent SDK, captures raw output,
then optionally canonicalizes that raw output into TargetAuditResult.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from model_backends import (
    claude_agent_sdk_query,
    openai_chat_completion,
    resolve_setting,
    run_subprocess,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one packet over a case split.")
    parser.add_argument("--manifest", required=True, help="Eval manifest yaml path.")
    parser.add_argument("--run-dir", required=True, help="Run directory initialized by run_experiment.py.")
    parser.add_argument("--split", required=True, help="Split name: dev/holdout/cross_repo/canary.")
    parser.add_argument("--candidate-id", help="Optional candidate id override.")
    parser.add_argument("--limit", type=int, help="Optional maximum number of cases to run.")
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
                raise SystemExit(f"Invalid JSON in {path} line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"Invalid object in {path} line {line_number}")
            rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def target_results_dir(run_dir: Path) -> Path:
    return run_dir / "target-results"


def candidate_target_results_dir(run_dir: Path, candidate_id: str) -> Path:
    return target_results_dir(run_dir) / candidate_id


def canonical_cache_path(run_dir: Path, candidate_id: str, case_id: str) -> Path:
    return candidate_target_results_dir(run_dir, candidate_id) / "canonicalized" / f"{case_id}.json"


def case_status_path(run_dir: Path, candidate_id: str, case_id: str) -> Path:
    return candidate_target_results_dir(run_dir, candidate_id) / "status" / f"{case_id}.status.json"


def resolved_target_repo_path(manifest: Dict[str, Any], run_dir: Path) -> Path:
    run_state_path = run_dir / "run-state.json"
    if run_state_path.exists():
        try:
            run_state = read_json(run_state_path)
        except Exception:
            run_state = {}
        target_project = run_state.get("current", {}).get("target_project", {})
        workspace_path = target_project.get("workspace_path")
        if workspace_path:
            return Path(str(workspace_path)).resolve()
    return Path(str(manifest["experiment"]["target_project"]["repo_path"])).resolve()


def safe_case_projection(case: Dict[str, Any]) -> Dict[str, Any]:
    repo = case.get("repo", {})
    entry = case.get("entry", {})
    expected = case.get("expected", {})
    return {
        "case_id": case.get("case_id"),
        "repo": {
            "url": repo.get("url"),
            "branch": repo.get("branch"),
        },
        "entry": {
            "name": entry.get("name"),
            "transport": entry.get("transport"),
            "language": entry.get("language"),
        },
        "hints": {
            "vulnerability_type": expected.get("vulnerability_type"),
            "notes": case.get("notes"),
            "key_anchor": expected.get("key_anchor"),
            "key_sink": expected.get("key_sink"),
        },
    }


def format_context(case: Dict[str, Any], manifest: Dict[str, Any], run_id: str) -> Dict[str, str]:
    repo = case.get("repo", {})
    entry = case.get("entry", {})
    return {
        "case_id": str(case.get("case_id", "")),
        "repo_url": str(repo.get("url", "")),
        "repo_branch": str(repo.get("branch", "")),
        "entry_name": str(entry.get("name", "")),
        "transport": str(entry.get("transport", "")),
        "language": str(entry.get("language", "")),
        "profile": str(manifest.get("experiment", {}).get("profile", "")),
        "run_id": run_id,
        "case_json": json.dumps(safe_case_projection(case), ensure_ascii=False, indent=2),
    }


def load_preloaded_files(cwd: Path, file_list: List[str]) -> str:
    sections: List[str] = []
    for item in file_list:
        path = (cwd / item).resolve() if not Path(item).is_absolute() else Path(item).resolve()
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        sections.append(f"## FILE: {path}\n\n{content}")
    return "\n\n".join(sections)


def render_template(template: str, context: Dict[str, str]) -> str:
    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(SafeDict(context))


def build_command(base_command: str, arg_templates: List[str], context: Dict[str, str]) -> List[str]:
    command = base_command.split()
    for item in arg_templates:
        rendered = render_template(item, context).strip()
        if rendered:
            command.append(rendered)
    return command


def ensure_target_result_shape(case: Dict[str, Any], payload: Dict[str, Any], raw_output_ref: str) -> Dict[str, Any]:
    payload.setdefault("case_id", case.get("case_id"))
    payload.setdefault(
        "entry",
        {
            "name": case.get("entry", {}).get("name"),
            "transport": case.get("entry", {}).get("transport"),
            "language": case.get("entry", {}).get("language"),
        },
    )
    payload.setdefault(
        "verdict",
        {
            "has_vulnerability": False,
            "status": "unknown",
            "confidence": 0.0,
            "summary": "",
        },
    )
    payload.setdefault(
        "evidence",
        {
            "files": [],
            "functions": [],
            "locations": [],
            "reasoning_mode": "report-derived",
            "notes": [],
        },
    )
    payload.setdefault("artifacts", {})
    payload["raw_output_ref"] = raw_output_ref
    return payload


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


def blank_candidate_score(candidate_id: str) -> Dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "splits": {
            "dev": blank_split_score(),
            "holdout": blank_split_score(),
            "cross_repo": blank_split_score(),
            "canary": blank_split_score(),
        },
    }


def default_canonicalizer_script() -> Path:
    return (Path(__file__).resolve().parent / "canonicalize_target_output.py").resolve()


def default_grade_script() -> Path:
    return (Path(__file__).resolve().parent / "grade_run.py").resolve()


def load_cached_result(run_dir: Path, candidate_id: str, case: Dict[str, Any]) -> Dict[str, Any] | None:
    path = canonical_cache_path(run_dir, candidate_id, str(case["case_id"]))
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:
        return None
    return ensure_target_result_shape(case, payload, str(payload.get("raw_output_ref", path)))


def write_case_status(
    run_dir: Path,
    candidate_id: str,
    case_id: str,
    payload: Dict[str, Any],
) -> None:
    write_json(case_status_path(run_dir, candidate_id, case_id), payload)


def run_external_canonicalizer(
    canonical_cfg: Dict[str, Any],
    case: Dict[str, Any],
    raw_file: Path,
    run_dir: Path,
    candidate_id: str,
) -> Dict[str, Any]:
    case_inputs_dir = run_dir / "case-inputs"
    case_file = case_inputs_dir / f"{case['case_id']}.json"
    write_json(case_file, case)

    canonical_dir = candidate_target_results_dir(run_dir, candidate_id) / "canonicalized"
    output_file = canonical_dir / f"{case['case_id']}.json"
    script_path = Path(canonical_cfg.get("script", str(default_canonicalizer_script()))).resolve()
    cwd = Path(canonical_cfg.get("cwd", str(Path.cwd()))).resolve()
    command = [
        sys.executable,
        str(script_path),
        "--case-file",
        str(case_file),
        "--raw-file",
        str(raw_file),
        "--output",
        str(output_file),
        "--mode",
        canonical_cfg.get("mode", "claude-agent-sdk-python"),
        "--cwd",
        str(cwd),
    ]
    for allowed_tool in canonical_cfg.get("allowed_tools", []):
        command.extend(["--allowed-tool", allowed_tool])
    if canonical_cfg.get("permission_mode"):
        command.extend(["--permission-mode", canonical_cfg["permission_mode"]])
    if canonical_cfg.get("prompt_file"):
        command.extend(["--prompt-file", canonical_cfg["prompt_file"]])
    if canonical_cfg.get("max_turns") is not None:
        command.extend(["--max-turns", str(canonical_cfg["max_turns"])])
    if canonical_cfg.get("timeout_seconds") is not None:
        command.extend(["--timeout-seconds", str(canonical_cfg["timeout_seconds"])])

    env_overrides: Dict[str, str | None] = {}
    mode = canonical_cfg.get("mode", "claude-agent-sdk-python")
    api_key = resolve_setting(canonical_cfg, "api_key")
    base_url = resolve_setting(canonical_cfg, "base_url")
    model = resolve_setting(canonical_cfg, "model")
    if mode == "openai-compatible-chat":
        if api_key:
            env_overrides["OPENAI_API_KEY"] = api_key
        if base_url:
            env_overrides["OPENAI_BASE_URL"] = base_url
        if model:
            env_overrides["OPENAI_MODEL"] = model
    else:
        if api_key:
            env_overrides["ANTHROPIC_API_KEY"] = api_key
        if base_url:
            env_overrides["ANTHROPIC_BASE_URL"] = base_url
        if model:
            env_overrides["ANTHROPIC_MODEL"] = model

    result = run_subprocess(command, Path.cwd(), env_overrides=env_overrides or None)
    if result.returncode != 0:
        raise RuntimeError(
            f"Canonicalization script failed for case {case['case_id']}:\n"
            f"command={' '.join(command)}\n"
            f"stderr={result.stderr}"
        )
    payload = read_json(output_file)
    return ensure_target_result_shape(case, payload, str(raw_file))


def run_grader(
    run_dir: Path,
    candidate_id: str,
    split: str,
    grade_cfg: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    grade_cfg = grade_cfg or {}
    script_path = Path(grade_cfg.get("script", str(default_grade_script()))).resolve()
    cases_path = run_dir / "splits" / f"{split}.jsonl"
    results_path = candidate_target_results_dir(run_dir, candidate_id) / f"{split}.results.jsonl"
    grading_dir = run_dir / "grading" / candidate_id
    per_case_output = grading_dir / f"{split}.grading.jsonl"
    scoreboard_output = grading_dir / f"{split}.score.json"

    command = [
        sys.executable,
        str(script_path),
        "--cases",
        str(cases_path),
        "--results",
        str(results_path),
        "--output",
        str(per_case_output),
        "--scoreboard-output",
        str(scoreboard_output),
        "--split",
        split,
    ]
    result = run_subprocess(command, Path.cwd())
    if result.returncode != 0:
        raise RuntimeError(
            f"Grader failed for split {split}:\n"
            f"command={' '.join(command)}\n"
            f"stderr={result.stderr}"
        )
    return read_json(scoreboard_output)


def normalize_split_score(scoreboard_fragment: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "accuracy": float(scoreboard_fragment.get("accuracy", 0.0) or 0.0),
        "precision": float(scoreboard_fragment.get("precision", 0.0) or 0.0),
        "recall": float(scoreboard_fragment.get("recall", 0.0) or 0.0),
        "f1": float(scoreboard_fragment.get("f1", 0.0) or 0.0),
        "evidence_adequacy": float(scoreboard_fragment.get("evidence_adequacy", 0.0) or 0.0),
        "chain_completeness": float(scoreboard_fragment.get("chain_completeness", 0.0) or 0.0),
        "high_confidence_false_positive_rate": float(
            scoreboard_fragment.get("high_confidence_false_positive_rate", 0.0) or 0.0
        ),
        "case_count": int(scoreboard_fragment.get("case_count", 0) or 0),
    }


def update_scoreboard(
    run_dir: Path,
    candidate_id: str,
    split: str,
    scoreboard_fragment: Dict[str, Any],
) -> Dict[str, Any]:
    scoreboard_path = run_dir / "scoreboard.json"
    scoreboard = read_json(scoreboard_path)
    split_score = normalize_split_score(scoreboard_fragment)
    current = scoreboard.get("current")
    if not isinstance(current, dict) or current.get("candidate_id") != candidate_id:
        current = blank_candidate_score(candidate_id)
        scoreboard["current"] = current
    current["splits"][split] = split_score

    if scoreboard.get("baseline", {}).get("candidate_id") == candidate_id:
        scoreboard["baseline"]["splits"][split] = split_score
    if scoreboard.get("best", {}).get("candidate_id") == candidate_id:
        scoreboard["best"]["splits"][split] = split_score

    write_json(scoreboard_path, scoreboard)
    return scoreboard


def update_run_state(
    run_dir: Path,
    candidate_id: str,
    split: str,
    success_count: int,
    failure_count: int,
    grading_score: Dict[str, Any],
) -> Dict[str, Any]:
    run_state_path = run_dir / "run-state.json"
    run_state = read_json(run_state_path)
    run_state["current"] = {"candidate_id": candidate_id}
    run_state.setdefault("supervisor", {})
    run_state["supervisor"]["status"] = "packet_completed"
    run_state["supervisor"]["last_split"] = split
    run_state["supervisor"]["last_success_count"] = success_count
    run_state["supervisor"]["last_failure_count"] = failure_count
    run_state["supervisor"]["last_split_score"] = normalize_split_score(grading_score)
    if failure_count:
        counters = run_state.setdefault("counters", {"keeps": 0, "discards": 0, "crashes": 0})
        counters["crashes"] = int(counters.get("crashes", 0) or 0)
    write_json(run_state_path, run_state)
    return run_state


def append_candidate_ledger(
    run_dir: Path,
    candidate_id: str,
    split: str,
    success_count: int,
    failure_count: int,
    grading_score: Dict[str, Any],
) -> None:
    ledger_entry = {
        "candidate_id": candidate_id,
        "split": split,
        "success_count": success_count,
        "failure_count": failure_count,
        "score": grading_score,
    }
    append_jsonl(run_dir / "candidate-ledger.jsonl", ledger_entry)


def invoke_cli_json(
    invocation: Dict[str, Any],
    case: Dict[str, Any],
    manifest: Dict[str, Any],
    run_id: str,
    run_dir: Path,
    candidate_id: str,
) -> Dict[str, Any]:
    context = format_context(case, manifest, run_id)
    target_repo_path = resolved_target_repo_path(manifest, run_dir)
    cwd = Path(render_template(invocation.get("cwd", str(target_repo_path)), context)).resolve()
    command = build_command(
        invocation["command"],
        invocation.get("per_case_args", []),
        context,
    )
    result = run_subprocess(command, cwd)
    raw_dir = candidate_target_results_dir(run_dir, candidate_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{case['case_id']}.stdout.txt"
    raw_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"Target project command failed for case {case['case_id']}:\n"
            f"command={' '.join(command)}\n"
            f"stderr={result.stderr}"
        )

    output_cfg = invocation.get("output", {})
    output_mode = output_cfg.get("mode", "json-stdout")
    if output_mode == "json-file":
        output_path = Path(render_template(output_cfg["path_template"], context)).resolve()
        payload = read_json(output_path)
    else:
        raw_payload = result.stdout
        canonical_cfg = invocation.get("canonicalization", {})
        if canonical_cfg.get("enabled"):
            raw_payload_path = raw_dir / f"{case['case_id']}.raw.txt"
            raw_payload_path.write_text(raw_payload, encoding="utf-8")
            return run_external_canonicalizer(canonical_cfg, case, raw_payload_path, run_dir, candidate_id)
        payload = json.loads(raw_payload)
    return ensure_target_result_shape(case, payload, str(raw_path))


def invoke_claude_agent_sdk_python(
    invocation: Dict[str, Any],
    case: Dict[str, Any],
    manifest: Dict[str, Any],
    run_id: str,
    run_dir: Path,
    candidate_id: str,
) -> Dict[str, Any]:
    context = format_context(case, manifest, run_id)
    target_repo_path = resolved_target_repo_path(manifest, run_dir)
    cwd = Path(render_template(invocation.get("cwd", str(target_repo_path)), context)).resolve()
    prompt_template = invocation.get(
        "prompt_template",
        "Use the target project to analyze this case.\n\nCase:\n{case_json}\n",
    )
    prompt = render_template(prompt_template, context)
    effective_invocation = dict(invocation)
    system_prompt = invocation.get("system_prompt")
    if system_prompt:
        effective_invocation["system_prompt"] = render_template(str(system_prompt), context)
    result_text = claude_agent_sdk_query(prompt, cwd, effective_invocation)
    raw_dir = candidate_target_results_dir(run_dir, candidate_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{case['case_id']}.agent-sdk.txt"
    raw_path.write_text(result_text, encoding="utf-8")

    canonical_cfg = invocation.get("canonicalization", {"enabled": True, "mode": "claude-agent-sdk-python", "cwd": str(cwd)})
    if canonical_cfg.get("enabled", True):
        return run_external_canonicalizer(canonical_cfg, case, raw_path, run_dir, candidate_id)

    payload = json.loads(result_text)
    return ensure_target_result_shape(case, payload, str(raw_path))


def invoke_openai_compatible_chat(
    invocation: Dict[str, Any],
    case: Dict[str, Any],
    manifest: Dict[str, Any],
    run_id: str,
    run_dir: Path,
    candidate_id: str,
) -> Dict[str, Any]:
    context = format_context(case, manifest, run_id)
    target_repo_path = resolved_target_repo_path(manifest, run_dir)
    cwd = Path(render_template(invocation.get("cwd", str(target_repo_path)), context)).resolve()
    prompt_template = invocation.get(
        "prompt_template",
        "Analyze exactly one case.\n\nCase:\n{case_json}\n",
    )
    preload_files = invocation.get("preload_files", [])
    if preload_files:
        context["preloaded_files"] = load_preloaded_files(cwd, list(preload_files))
    else:
        context["preloaded_files"] = ""
    prompt = render_template(prompt_template, context)
    effective_invocation = dict(invocation)
    system_prompt = invocation.get("system_prompt")
    if system_prompt:
        effective_invocation["system_prompt"] = render_template(str(system_prompt), context)
    result_text = openai_chat_completion(prompt, effective_invocation)

    raw_dir = candidate_target_results_dir(run_dir, candidate_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{case['case_id']}.openai.txt"
    raw_path.write_text(result_text, encoding="utf-8")

    canonical_cfg = invocation.get("canonicalization", {})
    if canonical_cfg.get("enabled"):
        raw_payload_path = raw_dir / f"{case['case_id']}.raw.txt"
        raw_payload_path.write_text(result_text, encoding="utf-8")
        return run_external_canonicalizer(canonical_cfg, case, raw_payload_path, run_dir, candidate_id)

    payload = json.loads(result_text)
    return ensure_target_result_shape(case, payload, str(raw_path))


def normalized_fallback_invocations(invocation: Dict[str, Any]) -> List[Dict[str, Any]]:
    fallbacks: List[Dict[str, Any]] = []
    singular = invocation.get("fallback_invocation")
    plural = invocation.get("fallback_invocations", [])
    if isinstance(singular, dict):
        fallbacks.append(singular)
    if isinstance(plural, list):
        fallbacks.extend(item for item in plural if isinstance(item, dict))
    return fallbacks


def invoke_target_project(
    invocation: Dict[str, Any],
    case: Dict[str, Any],
    manifest: Dict[str, Any],
    run_id: str,
    run_dir: Path,
    candidate_id: str,
) -> tuple[Dict[str, Any], str]:
    errors: List[str] = []
    invocation_chain = [dict(invocation), *normalized_fallback_invocations(invocation)]
    for index, candidate_invocation in enumerate(invocation_chain):
        mode = candidate_invocation.get("mode", "cli-json")
        try:
            if mode == "claude-agent-sdk-python":
                return (
                    invoke_claude_agent_sdk_python(candidate_invocation, case, manifest, run_id, run_dir, candidate_id),
                    mode,
                )
            if mode == "openai-compatible-chat":
                return (
                    invoke_openai_compatible_chat(candidate_invocation, case, manifest, run_id, run_dir, candidate_id),
                    mode,
                )
            if mode == "cli-json":
                return (
                    invoke_cli_json(candidate_invocation, case, manifest, run_id, run_dir, candidate_id),
                    mode,
                )
            raise RuntimeError(f"Unsupported invocation mode: {mode}")
        except Exception as exc:
            errors.append(f"{mode}[{index}]: {exc}")
    raise RuntimeError("All invocation backends failed:\n" + "\n".join(errors))


def main() -> int:
    args = parse_args()
    manifest = load_manifest(Path(args.manifest).resolve())
    run_dir = Path(args.run_dir).resolve()
    run_state = read_json(run_dir / "run-state.json")
    run_id = str(run_state["run_id"])
    candidate_id = str(args.candidate_id or run_state.get("current", {}).get("candidate_id", "baseline"))
    split_path = run_dir / "splits" / f"{args.split}.jsonl"
    cases = read_jsonl(split_path)
    if args.limit is not None:
        cases = cases[: args.limit]

    target_project = manifest.get("experiment", {}).get("target_project", {})
    invocation = target_project.get("invocation", {})
    execution_cfg = manifest.get("execution", {})
    retry_cfg = execution_cfg.get("case_retry", {})
    reuse_completed_cases = bool(execution_cfg.get("resume_completed_cases", True))
    max_attempts = int(invocation.get("max_attempts", retry_cfg.get("max_attempts", 1)) or 1)
    retry_backoff_seconds = float(
        invocation.get("retry_backoff_seconds", retry_cfg.get("backoff_seconds", 0.0)) or 0.0
    )

    canonical_results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for case in cases:
        case_id = str(case.get("case_id"))
        cached_result = load_cached_result(run_dir, candidate_id, case) if reuse_completed_cases else None
        if cached_result is not None:
            canonical_results.append(cached_result)
            write_case_status(
                run_dir,
                candidate_id,
                case_id,
                {
                    "case_id": case_id,
                    "split": args.split,
                    "candidate_id": candidate_id,
                    "status": "cached",
                    "attempt_count": 0,
                    "elapsed_seconds": 0.0,
                    "canonical_result_path": str(canonical_cache_path(run_dir, candidate_id, case_id)),
                },
            )
            continue

        started_at = time.monotonic()
        last_error: str | None = None
        completed = False
        for attempt in range(1, max_attempts + 1):
            try:
                result, backend_used = invoke_target_project(invocation, case, manifest, run_id, run_dir, candidate_id)

                write_json(canonical_cache_path(run_dir, candidate_id, case_id), result)
                canonical_results.append(result)
                elapsed_seconds = round(time.monotonic() - started_at, 3)
                write_case_status(
                    run_dir,
                    candidate_id,
                    case_id,
                    {
                        "case_id": case_id,
                        "split": args.split,
                        "candidate_id": candidate_id,
                        "status": "completed",
                        "attempt_count": attempt,
                        "elapsed_seconds": elapsed_seconds,
                        "backend_used": backend_used,
                        "raw_output_ref": result.get("raw_output_ref"),
                        "canonical_result_path": str(canonical_cache_path(run_dir, candidate_id, case_id)),
                    },
                )
                completed = True
                break
            except Exception as exc:
                last_error = str(exc)
                elapsed_seconds = round(time.monotonic() - started_at, 3)
                write_case_status(
                    run_dir,
                    candidate_id,
                    case_id,
                    {
                        "case_id": case_id,
                        "split": args.split,
                        "candidate_id": candidate_id,
                        "status": "retrying" if attempt < max_attempts else "failed",
                        "attempt_count": attempt,
                        "elapsed_seconds": elapsed_seconds,
                        "last_error": last_error,
                    },
                )
                if attempt < max_attempts and retry_backoff_seconds > 0:
                    time.sleep(retry_backoff_seconds)

        if not completed:
            failures.append(
                {
                    "case_id": case_id,
                    "split": args.split,
                    "attempt_count": max_attempts,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    "error": last_error or "unknown error",
                    "status_path": str(case_status_path(run_dir, candidate_id, case_id)),
                }
            )

    results_dir = candidate_target_results_dir(run_dir, candidate_id)
    results_path = results_dir / f"{args.split}.results.jsonl"
    failures_path = results_dir / f"{args.split}.failures.jsonl"
    write_jsonl(results_path, canonical_results)
    write_jsonl(failures_path, failures)

    grading_score = run_grader(run_dir, candidate_id, args.split)
    update_scoreboard(run_dir, candidate_id, args.split, grading_score)
    update_run_state(
        run_dir,
        candidate_id,
        args.split,
        len(canonical_results),
        len(failures),
        grading_score,
    )
    append_candidate_ledger(
        run_dir,
        candidate_id,
        args.split,
        len(canonical_results),
        len(failures),
        grading_score,
    )

    print(
        json.dumps(
            {
                "run_id": run_id,
                "candidate_id": candidate_id,
                "split": args.split,
                "success_count": len(canonical_results),
                "failure_count": len(failures),
                "results_path": str(results_path),
                "failures_path": str(failures_path),
                "grading_score": grading_score,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
