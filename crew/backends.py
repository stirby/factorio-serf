"""Model backends. Both run one agent "turn": a prompt in, a tool-use loop, done.

- ClaudeCodeBackend: the Claude Agent SDK on the local Claude Code login (subscription, no API billing).
  Claude Code keeps the session and compacts it on its own.
- ApiBackend: the Anthropic API with ANTHROPIC_API_KEY (pay per use). Append-only history; when it gets
  long, the agent starts a fresh conversation seeded with its notes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .tools import TOOLS, run_tool

if TYPE_CHECKING:
    from .agent import Agent

log = logging.getLogger("crew.backend")

MAX_STEPS_PER_TURN = 60


@dataclass
class TurnStats:
    steps: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


class ClaudeCodeBackend:
    def __init__(self, agent: "Agent", system: str, workdir: Path, tools=None, max_steps: int = MAX_STEPS_PER_TURN):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

        self.agent = agent
        tools = tools or TOOLS
        sdk_tools = []
        for t in tools:
            def make(name):
                async def handler(args):
                    out = await run_tool(agent, name, args)
                    return {"content": [{"type": "text", "text": out}]}
                return handler
            sdk_tools.append(tool(t.name, t.description, t.schema)(make(t.name)))
        server = create_sdk_mcp_server("game", tools=sdk_tools)
        workdir.mkdir(parents=True, exist_ok=True)
        cfg = agent.cfg
        self.options = ClaudeAgentOptions(
            system_prompt=system,
            mcp_servers={"game": server},
            tools=[],  # no built-in Bash/Read/etc: this agent only plays the game
            allowed_tools=[f"mcp__game__{t.name}" for t in tools],
            setting_sources=[],  # don't pick up the user's CLAUDE.md, hooks or settings
            model=cfg.model,
            effort=cfg.effort,
            cwd=str(workdir),
            max_turns=max_steps,
            stderr=lambda line: log.debug("[%s cli] %s", agent.name, line),
        )
        self.client = None

    async def start(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient
        self.client = ClaudeSDKClient(self.options)
        await self.client.connect()

    async def close(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass

    async def reset(self) -> None:
        """Start a fresh conversation (notes and the board carry what matters)."""
        await self.close()
        self.client = None
        await self.start()

    async def interrupt(self) -> None:
        if self.client:
            try:
                await self.client.interrupt()
            except Exception:
                pass

    async def set_model(self, model: str) -> None:
        if self.client:
            await self.client.set_model(model)

    async def turn(self, prompt: str) -> TurnStats:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

        stats = TurnStats()
        await self.client.query(prompt)
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        self.agent.log_thought(b.text)
                    elif isinstance(b, ToolUseBlock):
                        stats.steps += 1
            elif isinstance(msg, ResultMessage):
                stats.cost_usd = msg.total_cost_usd or 0.0
                u = msg.usage or {}
                stats.input_tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                                      + u.get("cache_creation_input_tokens", 0))
                stats.output_tokens = u.get("output_tokens", 0)
                if msg.is_error:
                    stats.error = msg.subtype
        return stats


class ApiBackend:
    RESET_AT_INPUT_TOKENS = 160_000

    def __init__(self, agent: "Agent", system: str, workdir: Path, tools=None, max_steps: int = MAX_STEPS_PER_TURN):
        import anthropic
        self.max_steps = max_steps
        self.anthropic = anthropic
        self.client = anthropic.AsyncAnthropic()
        self.agent = agent
        self.system = system
        self.messages: list = []
        self.tools = [{"name": t.name, "description": t.description, "input_schema": t.schema}
                      for t in (tools or TOOLS)]
        self.use_fallbacks = True

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        await self.client.close()

    async def interrupt(self) -> None:
        pass

    async def set_model(self, model: str) -> None:
        pass  # read from cfg on every request

    async def reset(self) -> None:
        self.messages = []

    async def _create(self):
        cfg = self.agent.cfg
        kw = dict(model=cfg.model, max_tokens=16000, system=self.system, tools=self.tools,
                  messages=self.messages, cache_control={"type": "ephemeral"})
        if cfg.effort:
            kw["output_config"] = {"effort": cfg.effort}
        if self.use_fallbacks and cfg.model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            try:
                return await self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            except self.anthropic.BadRequestError as e:
                log.warning("fallbacks not accepted (%s); continuing without", e.message)
                self.use_fallbacks = False
        return await self.client.messages.create(**kw)

    async def turn(self, prompt: str) -> TurnStats:
        stats = TurnStats()
        if not self.messages:
            prompt = "(new conversation; your notes carry over what you knew)\n" + prompt
        self.messages.append({"role": "user", "content": prompt})
        last_input = 0
        for _ in range(self.max_steps):
            try:
                resp = await self._create()
            except self.anthropic.RateLimitError:
                stats.error = "rate limited"
                break
            except self.anthropic.APIStatusError as e:
                stats.error = f"api error {e.status_code}: {e.message}"
                break
            except self.anthropic.APIConnectionError:
                stats.error = "api connection error"
                break
            u = resp.usage
            last_input = (u.input_tokens or 0) + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
            stats.input_tokens += last_input
            stats.output_tokens += u.output_tokens or 0
            self.messages.append({"role": "assistant", "content": resp.content})  # keep thinking blocks intact
            if resp.stop_reason == "refusal":
                stats.error = "refusal"
                break
            uses = [b for b in resp.content if b.type == "tool_use"]
            for b in resp.content:
                if b.type == "text" and b.text.strip():
                    self.agent.log_thought(b.text)
            if resp.stop_reason != "tool_use" or not uses:
                break
            results = []
            for b in uses:
                stats.steps += 1
                out = await run_tool(self.agent, b.name, b.input if isinstance(b.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            self.messages.append({"role": "user", "content": results})
        if last_input > self.RESET_AT_INPUT_TOKENS:
            log.info("%s: context at %d tokens, starting a fresh conversation", self.agent.name, last_input)
            self.messages = []
        return stats


def make_backend(agent: "Agent", system: str, workdir: Path, tools=None, max_steps: int = MAX_STEPS_PER_TURN):
    if agent.cfg.backend == "api":
        return ApiBackend(agent, system, workdir, tools, max_steps)
    if agent.cfg.backend in ("claude-code", "claude_code", "subscription"):
        return ClaudeCodeBackend(agent, system, workdir, tools, max_steps)
    raise ValueError(f"unknown backend {agent.cfg.backend!r} (use claude-code or api)")
