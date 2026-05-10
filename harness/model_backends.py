#!/usr/bin/env python3
"""
Reusable model backend helpers for target invocation and canonicalization.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager, nullcontext
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
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Subprocess timed out after {timeout_seconds} seconds: {' '.join(command)}"
        ) from exc


def openai_chat_completion(prompt: str, config: Dict[str, Any]) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("openai package is not installed.") from exc

    api_key = resolve_setting(config, "api_key")
    base_url = resolve_setting(config, "base_url")
    model = resolve_setting(config, "model")
    if not api_key:
        raise RuntimeError("Missing api_key/api_key_env for openai-compatible backend.")
    if not base_url:
        raise RuntimeError("Missing base_url/base_url_env for openai-compatible backend.")
    if not model:
        raise RuntimeError("Missing model/model_env for openai-compatible backend.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = []
    system_prompt = config.get("system_prompt")
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": prompt})
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(config.get("temperature", 0.0) or 0.0),
        timeout=float(config["timeout_seconds"]) if config.get("timeout_seconds") is not None else None,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("openai-compatible backend returned empty content.")
    return str(content)


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


def configure_sdk_env(config: Dict[str, Any]) -> None:
    for key, value in _claude_env_overrides(config).items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def claude_agent_sdk_query(
    prompt: str,
    cwd: Path,
    config: Dict[str, Any],
    heartbeat_label: str = "SDK query",
    skip_env_setup: bool = False,
) -> str:
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
        from claude_agent_sdk.types import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
        )  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("claude-agent-sdk is not installed.") from exc

    allowed_tools = config.get("allowed_tools")
    permission_mode = config.get("permission_mode")
    model = resolve_setting(config, "model")
    system_prompt = config.get("system_prompt")
    max_turns = config.get("max_turns")
    permission_prompt_tool = config.get("permission_prompt_tool")
    permission_mode_tool_name = config.get("permission_mode_tool_name")
    thinking = config.get("thinking")
    effort = config.get("effort")
    timeout_seconds = (
        float(config["timeout_seconds"])
        if config.get("timeout_seconds") is not None
        else None
    )
    quiet = bool(config.get("quiet", False))
    heartbeat_interval = float(config.get("heartbeat_interval", 60) or 60)
    max_timeout_extensions = int(config.get("max_timeout_extensions", 0) or 0)

    async def _heartbeat_loop() -> None:
        start = asyncio.get_event_loop().time()
        try:
            while True:
                await asyncio.sleep(heartbeat_interval)
                elapsed = int(asyncio.get_event_loop().time() - start)
                sys.stderr.write(f"[SDK heartbeat] {heartbeat_label}: {elapsed}s elapsed, cwd={cwd}\n")
                sys.stderr.flush()
        except asyncio.CancelledError:
            return

    async def _stream_query() -> str:
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
        if thinking is not None:
            options_kwargs["thinking"] = thinking
        if effort is not None:
            options_kwargs["effort"] = effort
        options = ClaudeAgentOptions(**options_kwargs)

        if not quiet:
            sys.stderr.write(f"[SDK] {heartbeat_label}: query start, cwd={cwd}\n")
            sys.stderr.flush()

        result_text = ""
        turn = 0
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn += 1
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text and not quiet:
                        sys.stderr.write(f"[SDK turn {turn}] {block.text}\n")
                        sys.stderr.flush()
                    elif isinstance(block, ToolUseBlock) and not quiet:
                        _input = {k: v for k, v in block.input.items() if k != "command"} if isinstance(block.input, dict) else {}
                        _cmd = block.input.get("command", "") if isinstance(block.input, dict) else ""
                        _desc = _cmd[:120] if _cmd else str(_input)[:120]
                        sys.stderr.write(f"[SDK turn {turn}] tool: {block.name}({_desc})\n")
                        sys.stderr.flush()
            elif isinstance(message, ResultMessage):
                result_text = message.result if message.result else ""
                if not quiet:
                    sys.stderr.write(f"[SDK] {heartbeat_label}: done, result length={len(result_text)}\n")
                    sys.stderr.flush()
            elif hasattr(message, "result") and message.result is not None:
                result_text = message.result
                if not quiet:
                    sys.stderr.write(f"[SDK] {heartbeat_label}: done (fallback), result length={len(str(result_text))}\n")
                    sys.stderr.flush()

        return result_text

    env_context = nullcontext() if skip_env_setup else temporary_environment(_claude_env_overrides(config))
    with env_context:
        async def _run_with_timeout() -> str:
            heartbeat = None if quiet else asyncio.create_task(_heartbeat_loop())
            query_task = asyncio.create_task(_stream_query())
            try:
                if timeout_seconds is None:
                    return await query_task
                extensions_used = 0
                while True:
                    try:
                        return await asyncio.wait_for(asyncio.shield(query_task), timeout=timeout_seconds)
                    except asyncio.TimeoutError:
                        if extensions_used >= max_timeout_extensions:
                            query_task.cancel()
                            raise
                        extensions_used += 1
                        sys.stderr.write(
                            f"[SDK heartbeat] {heartbeat_label}: timeout reached, extending "
                            f"{extensions_used}/{max_timeout_extensions}\n"
                        )
                        sys.stderr.flush()
            finally:
                if not query_task.done():
                    query_task.cancel()
                    try:
                        await query_task
                    except asyncio.CancelledError:
                        pass
                if heartbeat is not None:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass

        try:
            return asyncio.run(_run_with_timeout())
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise RuntimeError(
                f"claude-agent-sdk query timed out after {timeout_seconds} seconds "
                f"with {max_timeout_extensions} extension(s)."
            ) from exc
