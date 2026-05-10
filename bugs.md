# Known Pitfalls

## Runtime

- This machine still resolves plain `python` to `3.9.x`. Use `py -3.14` for this project.
- `claude-agent-sdk-python` is the only supported agent-session path.
- On Windows, claude-agent-sdk requires git-bash. Set `CLAUDE_CODE_GIT_BASH_PATH` to point to `bash.exe`.

## Endpoint Compatibility

- Endpoint: `https://api.deepseek.com/anthropic`
- Model: `deepseek-v4-pro`

## Evaluation

- Missing target results must count as failed cases. `grade_run.py` already treats missing results as failures.
- Canonicalizer output is not always pure JSON. `canonicalize_target_output.py` extracts JSON from fenced blocks or the first valid JSON region before failing.
- For long runs, keep `resume_completed_cases: true` together with per-case `timeout_seconds`, `max_attempts`, and `retry_backoff_seconds`.
- Target results, canonicalized outputs, and status files must remain isolated per candidate. Reusing one shared results directory across candidates will contaminate later scoring.
- In staged candidate evaluation, the intermediate dev-gate decision must only evaluate already executed splits. Calling the full keep gate before holdout/cross_repo runs can discard a promising candidate because those unexecuted split scores are still blank.
- `run_packet.py` must preserve `run-state.current.target_project` after each split. Otherwise staged follow-up splits can silently evaluate the original target project instead of the prepared candidate workspace.
- OpenAI-compatible canonicalization must receive `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`. Passing only Anthropic-style environment variables breaks `canonicalize_target_output.py --mode openai-compatible-chat`.
- Keep `openai-compatible-chat` as a plain fallback/model-call backend when it is referenced by manifests. Removing the backend while leaving fallback manifests in place makes target invocation fail after the SDK path errors.
- If `run_packet.py` accepts a canonicalization mode, `canonicalize_target_output.py` must accept the same mode. Otherwise the manifest validates conceptually but fails only after the target project has already spent a model call.
- Round-level resume should count completed non-baseline decision files and continue from the next round. Do not delete incomplete candidate or packet directories automatically; preserve them for debugging and let the next candidate id advance.
- Long SDK calls should use `heartbeat_interval` and `max_timeout_extensions` when configured. The heartbeat task must always be cancelled in a `finally` block to avoid leaking async tasks after return or timeout.
- Do not call `os.chdir()` inside concurrent SDK case execution. Use the SDK `cwd` option and preconfigure SDK environment once per packet, otherwise parallel cases can run in the wrong repository.
- Scoreboard initialization must deep-create baseline/best/current split dictionaries. Shallow copies can make split counters or scores appear to change across candidates.
- Shared harness helpers must not include default artifact cleanup. Cleanup of candidate, packet, grading, or target-result directories is destructive enough that it should remain explicit and user-approved.
- Grader match-rule settings must be wired into `grade_run.py`. If `require_type_match_when_available` is configured but not passed to the grader, wrong vulnerability types can be counted as true positives.
- `require_evidence_for_high_confidence` must be enforced by the grader, not only documented in manifest. High-confidence vulnerable verdicts without file/function/location evidence should fail grading.

## Candidate Workspaces

- Automatic optimization must edit a prepared candidate workspace, not the original target project directory.
- When the source candidate is `baseline` and no workspace exists yet, packet proposal falls back to the original target project directory for editable-file discovery.
