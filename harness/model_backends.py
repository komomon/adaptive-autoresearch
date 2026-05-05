#!/usr/bin/env python3
"""
Reusable model backend helpers for target invocation and canonicalization.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List


@contextmanager
def temporary_environment(overrides: Dict[str, str | None]) -> Iterator[None]:
    previous: Dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve_setting(config: Dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value:
        return str(value)
    env_name = config.get(f"{key}_env")
    if env_name:
        env_value = os.environ.get(str(env_name))
        if env_value:
            return env_value
    return None


def run_subprocess(
    command: List[str],
    cwd: Path,
    env_overrides: Dict[str, str | None] | None = None,
    timeout_seconds: float | None = None,
) -> "subprocess.CompletedProcess[str]":
    import subprocess

    env = os.environ.copy()
    if env_overrides:
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Subprocess timed out after {timeout_seconds} seconds: {' '.join(command)}"
        ) from exc


def _claude_env_overrides(config: Dict[str, Any]) -> Dict[str, str | None]:
    overrides: Dict[str, str | None] = {}
    api_key = resolve_setting(config, "api_key")
    base_url = resolve_setting(config, "base_url")
    model = resolve_setting(config, "model")
    if api_key:
        overrides["ANTHROPIC_API_KEY"] = api_key
    if base_url:
        overrides["ANTHROPIC_BASE_URL"] = base_url
    if model:
        overrides["ANTHROPIC_MODEL"] = model
    return overrides


def claude_agent_sdk_query(prompt: str, cwd: Path, config: Dict[str, Any]) -> str:
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("claude-agent-sdk is not installed.") from exc

    allowed_tools = config.get("allowed_tools")
    permission_mode = config.get("permission_mode")
    model = resolve_setting(config, "model")
    system_prompt = config.get("system_prompt")
    max_turns = config.get("max_turns")
    permission_prompt_tool = config.get("permission_prompt_tool")
    permission_mode_tool_name = config.get("permission_mode_tool_name")
    timeout_seconds = (
        float(config["timeout_seconds"])
        if config.get("timeout_seconds") is not None
        else None
    )

    async def _run_query() -> str:
        previous_cwd = Path.cwd()
        os.chdir(cwd)
        try:
            options_kwargs: Dict[str, Any] = {"cwd": str(cwd)}
            if allowed_tools:
                options_kwargs["allowed_tools"] = allowed_tools
            if permission_mode:
                options_kwargs["permission_mode"] = permission_mode
            if model:
                options_kwargs["model"] = model
            if system_prompt:
                options_kwargs["system_prompt"] = str(system_prompt)
            if max_turns is not None:
                options_kwargs["max_turns"] = int(max_turns)
            if permission_prompt_tool is not None:
                options_kwargs["permission_prompt_tool"] = permission_prompt_tool
            if permission_mode_tool_name is not None:
                options_kwargs["permission_mode_tool_name"] = permission_mode_tool_name
            options = ClaudeAgentOptions(**options_kwargs)
            result_text = ""
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "result"):
                    result_text = message.result
            return result_text
        finally:
            os.chdir(previous_cwd)

    with temporary_environment(_claude_env_overrides(config)):
        async def _run_with_timeout() -> str:
            if timeout_seconds is None:
                return await _run_query()
            return await asyncio.wait_for(_run_query(), timeout=timeout_seconds)

        try:
            return asyncio.run(_run_with_timeout())
        except TimeoutError as exc:
            raise RuntimeError(
                f"claude-agent-sdk query timed out after {timeout_seconds} seconds."
            ) from exc
