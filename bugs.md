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

## Candidate Workspaces

- Automatic optimization must edit a prepared candidate workspace, not the original target project directory.
- When the source candidate is `baseline` and no workspace exists yet, packet proposal falls back to the original target project directory for editable-file discovery.
