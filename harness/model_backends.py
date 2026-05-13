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


def configure_sdk_env(config: Dict[str, Any]) -> None:
    """Set SDK environment variables once before spawning concurrent threads."""
    overrides = _claude_env_overrides(config)
    for key, value in overrides.items():
        if value is not None:
            os.environ[key] = value


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


def claude_agent_sdk_query(
    prompt: str,
    cwd: Path,
    config: Dict[str, Any],
    heartbeat_label: str = "LLM query",
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
    timeout_seconds = (
        float(config["timeout_seconds"])
        if config.get("timeout_seconds") is not None
        else None
    )
    quiet = bool(config.get("quiet", False))
    max_extensions = int(config.get("max_timeout_extensions", 1))
    heartbeat_interval = float(config.get("heartbeat_interval", 60))

    sdk_status = {"waiting_first_message": True, "turns": 0, "last_tool": "", "last_tool_time": 0.0}

    async def _heartbeat_loop() -> None:
        start = asyncio.get_event_loop().time()
        try:
            while True:
                await asyncio.sleep(heartbeat_interval)
                elapsed = int(asyncio.get_event_loop().time() - start)
                parts = [f"{heartbeat_label} -- {elapsed}s elapsed"]
                if sdk_status["waiting_first_message"]:
                    parts.append("waiting for first response (model thinking or API queued)")
                else:
                    parts.append(f"turns={sdk_status['turns']}")
                    if sdk_status["last_tool"]:
                        tool_elapsed = int(asyncio.get_event_loop().time() - sdk_status["last_tool_time"])
                        parts.append(f"last_tool={sdk_status['last_tool']} ({tool_elapsed}s ago)")
                sys.stderr.write(f"  [heartbeat] {' | '.join(parts)}\n")
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
        if config.get("thinking") is not None:
            options_kwargs["thinking"] = config["thinking"]
        if config.get("effort") is not None:
            options_kwargs["effort"] = config["effort"]
        options = ClaudeAgentOptions(**options_kwargs)

        if not quiet:
            sys.stderr.write(f"[SDK] query start, cwd={cwd}\n")
            sys.stderr.flush()

        result_text = ""
        turn = 0
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                sdk_status["waiting_first_message"] = False
                turn += 1
                sdk_status["turns"] = turn
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text and not quiet:
                        sys.stderr.write(f"[SDK turn {turn}] {block.text}\n")
                        sys.stderr.flush()
                    elif isinstance(block, ToolUseBlock) and not quiet:
                        _input = {k: v for k, v in block.input.items() if k != "command"} if isinstance(block.input, dict) else {}
                        _cmd = block.input.get("command", "") if isinstance(block.input, dict) else ""
                        _desc = _cmd[:120] if _cmd else str(_input)[:120]
                        sdk_status["last_tool"] = f"{block.name}({_desc[:60]})"
                        sdk_status["last_tool_time"] = asyncio.get_event_loop().time()
                        sys.stderr.write(f"[SDK turn {turn}] tool: {block.name}({_desc})\n")
                        sys.stderr.flush()
            elif isinstance(message, ResultMessage):
                result_text = message.result if message.result else ""
                if not quiet:
                    sys.stderr.write(f"[SDK] done, result length={len(result_text)}\n")
                    sys.stderr.flush()
            elif hasattr(message, "result") and message.result is not None:
                result_text = message.result
                if not quiet:
                    sys.stderr.write(f"[SDK] done (fallback), result length={len(str(result_text))}\n")
                    sys.stderr.flush()

        return result_text

    env_ctx = nullcontext() if skip_env_setup else temporary_environment(_claude_env_overrides(config))
    with env_ctx:
        async def _run_with_heartbeat_and_extend() -> str:
            if timeout_seconds is None:
                heartbeat = asyncio.create_task(_heartbeat_loop())
                try:
                    return await _stream_query()
                finally:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass

            extensions_used = 0
            while True:
                sdk_status.update({"waiting_first_message": True, "turns": 0, "last_tool": "", "last_tool_time": 0.0})
                heartbeat = asyncio.create_task(_heartbeat_loop())
                try:
                    return await asyncio.wait_for(_stream_query(), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
                    if extensions_used < max_extensions:
                        extensions_used += 1
                        sys.stderr.write(
                            f"  [heartbeat] {heartbeat_label} -- timeout expired, "
                            f"auto-extending ({extensions_used}/{max_extensions})\n"
                        )
                        sys.stderr.flush()
                    else:
                        raise
                finally:
                    if not heartbeat.done():
                        heartbeat.cancel()
                        try:
                            await heartbeat
                        except asyncio.CancelledError:
                            pass

        try:
            return asyncio.run(_run_with_heartbeat_and_extend())
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise RuntimeError(
                f"claude-agent-sdk query timed out after {timeout_seconds}s"
                f" (+{max_extensions} extensions) for {heartbeat_label}."
            ) from exc
