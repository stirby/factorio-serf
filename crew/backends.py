"""Model backends. Both run one agent "turn": a prompt in, a tool-use loop, done.

- ClaudeCodeBackend: the Claude Agent SDK on the local Claude Code login (subscription, no API billing).
  Claude Code keeps the session and compacts it on its own.
- ApiBackend: the Anthropic API with ANTHROPIC_API_KEY (pay per use). Append-only history; when it gets
  long, the agent starts a fresh conversation seeded with its notes.
- OpenAIBackend: any OpenAI-compatible chat-completions endpoint (Vercel AI Gateway, OpenAI, local servers),
  e.g. DeepSeek through the gateway. Same append-only history and reset; cost from the provider's price list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
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
            settings=json.dumps({"fastMode": cfg.fast}),  # the SDK only allows fast mode as a flag setting
            cwd=str(workdir),
            max_turns=max_steps,
            stderr=lambda line: log.debug("[%s cli] %s", agent.name, line),
        )
        self.client = None

    async def start(self) -> None:
        from claude_agent_sdk import ClaudeSDKClient
        self.client = ClaudeSDKClient(self.options)
        await self.client.connect()
        self._session_cost = 0.0  # the SDK reports a running total per session

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

    async def set_fast(self, on: bool) -> None:
        self.options.settings = json.dumps({"fastMode": on})  # for the next start()/reset()
        if self.client:
            # The SDK has no wrapper for this control request yet; the CLI merges it into its flag settings.
            await self.client._query._send_control_request({"subtype": "apply_flag_settings",
                                                            "settings": {"fastMode": on}})

    async def turn(self, prompt: str) -> TurnStats:
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

        stats = TurnStats()
        await self.client.query(prompt)
        async for msg in self.client.receive_response():
            if isinstance(msg, SystemMessage):
                # e.g. "Fast mode disabled · usage credits exhausted": the request still ran, at standard speed
                if msg.subtype == "notification" and str(msg.data.get("key", "")).startswith("fast-mode"):
                    await self.agent.notice(msg.data.get("text") or msg.data["key"])
            elif isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        self.agent.log_thought(b.text)
                        if "hit your session limit" in b.text or "usage limit" in b.text.lower():
                            stats.error = "usage_limit"  # the subscription ran out: not a model answer
                    elif isinstance(b, ToolUseBlock):
                        stats.steps += 1
            elif isinstance(msg, ResultMessage):
                # total_cost_usd is cumulative for this client session; a turn costs the difference.
                total = msg.total_cost_usd or 0.0
                stats.cost_usd = max(0.0, total - getattr(self, "_session_cost", 0.0))
                self._session_cost = total
                u = msg.usage or {}
                stats.input_tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                                      + u.get("cache_creation_input_tokens", 0))
                stats.output_tokens = u.get("output_tokens", 0)
                if msg.is_error and stats.error != "usage_limit":
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

    async def set_fast(self, on: bool) -> None:
        pass  # read from cfg on every request

    async def reset(self) -> None:
        self.messages = []

    async def _create(self):
        cfg = self.agent.cfg
        kw = dict(model=cfg.model, max_tokens=16000, system=self.system, tools=self.tools,
                  messages=self.messages, cache_control={"type": "ephemeral"})
        if cfg.effort:
            kw["output_config"] = {"effort": cfg.effort}
        betas = []
        if cfg.fast:
            betas.append("fast-mode-2026-02-01")
            kw["speed"] = "fast"
        if self.use_fallbacks and cfg.model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            try:
                return await self.client.beta.messages.create(
                    betas=betas + ["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            except self.anthropic.BadRequestError as e:
                log.warning("fallbacks not accepted (%s); continuing without", e.message)
                self.use_fallbacks = False
        if betas:
            return await self.client.beta.messages.create(betas=betas, **kw)
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


GATEWAY_HOST = "ai-gateway.vercel.sh"
_PRICES: dict[tuple[str, str], dict | None] = {}  # (base_url, model) -> per-token prices, fetched once
_PRICE_LOCK = asyncio.Lock()


def _rates(pricing: dict | None, now: float | None = None) -> dict | None:
    """Per-token input/output/cache-read rates. US regional prices when listed (we run in the US), else the
    default ones, doubled inside a listed peak window."""
    if not pricing:
        return None
    region = (pricing.get("regional") or {}).get("us")
    p = region or pricing
    try:
        r = {"input": float(p["input"]), "output": float(p["output"])}
    except (KeyError, TypeError, ValueError):
        return None
    r["cache_read"] = float(p.get("input_cache_read") or r["input"])
    peak = pricing.get("peak_pricing")
    if peak and not region:
        t = time.gmtime(now if now is not None else time.time())
        minute, dow = t.tm_hour * 60 + t.tm_min, t.tm_wday + 1  # ISO: Monday = 1
        for w in peak.get("windows") or []:
            if (w.get("start_minute_utc", 0) <= minute < w.get("end_minute_utc", 1440)
                    and dow in (w.get("days_of_week") or range(1, 8))):
                m = float(peak.get("multiplier", 1))
                r = {k: v * m for k, v in r.items()}
                break
    return r


def _usage_cost(usage, rates: dict | None) -> float | None:
    """Cost of one response: a provider-reported cost if there is one, else tokens x rates."""
    if usage is None:
        return 0.0
    extra = getattr(usage, "model_extra", None) or {}
    for k in ("cost", "cost_usd", "total_cost"):
        if isinstance(extra.get(k), (int, float)):
            return float(extra[k])
    if not rates:
        return None
    prompt = usage.prompt_tokens or 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = min(getattr(details, "cached_tokens", 0) or 0, prompt)
    return ((prompt - cached) * rates["input"] + cached * rates["cache_read"]
            + (usage.completion_tokens or 0) * rates["output"])


class OpenAIBackend:
    """Chat-completions tool loop for OpenAI-compatible providers (DeepSeek etc. via the Vercel AI Gateway)."""
    RESET_AT_INPUT_TOKENS = 160_000

    def __init__(self, agent: "Agent", system: str, workdir: Path, tools=None, max_steps: int = MAX_STEPS_PER_TURN):
        import openai
        self.openai = openai
        self.agent = agent
        self.max_steps = max_steps
        cfg = agent.cfg
        self.base_url = cfg.base_url or None
        env = cfg.api_key_env or ("AI_GATEWAY_API_KEY" if self.base_url and GATEWAY_HOST in self.base_url
                                  else "OPENAI_API_KEY")
        key = os.environ.get(env)
        if not key:
            raise ValueError(f"backend openai for {agent.name}: set {env} (e.g. in ~/.config/factorio-serf/env)")
        self.client = openai.AsyncOpenAI(api_key=key, base_url=self.base_url)
        self.system = system
        self.messages: list[dict] = []
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.schema}} for t in (tools or TOOLS)]
        self.send_effort = True  # reasoning_effort, until the provider rejects it
        self.keep_reasoning = True  # send reasoning fields back, until the provider rejects them
        self._warned: set[str] = set()

    def _warn_once(self, key: str, msg: str, *args) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        await self.client.close()

    async def interrupt(self) -> None:
        pass

    async def set_model(self, model: str) -> None:
        pass  # read from cfg on every request

    async def set_fast(self, on: bool) -> None:
        pass  # no fast mode on OpenAI-compatible endpoints (the chat command refuses it)

    async def reset(self) -> None:
        self.messages = []

    async def _rates(self) -> dict | None:
        model = self.agent.cfg.model
        key = (self.base_url or "", model)
        if key not in _PRICES:
            async with _PRICE_LOCK:
                if key not in _PRICES:
                    found = None
                    try:
                        page = await self.client.models.list()
                        for m in page.data:
                            if m.id == model:
                                found = (getattr(m, "model_extra", None) or {}).get("pricing")
                                break
                    except Exception as e:
                        log.warning("price list unavailable from %s: %r", self.base_url, e)
                    _PRICES[key] = found
        return _rates(_PRICES[key])

    def _strip_reasoning(self) -> None:
        for m in self.messages:
            if m.get("role") == "assistant":
                for k in [k for k in m if k.startswith("reasoning")]:
                    del m[k]

    async def _create(self):
        cfg = self.agent.cfg
        kw = dict(model=cfg.model, max_tokens=16000, tools=self.tools,
                  messages=[{"role": "system", "content": self.system}] + self.messages)
        if cfg.effort and self.send_effort:
            kw["reasoning_effort"] = cfg.effort
        for _ in range(3):
            try:
                return await self.client.chat.completions.create(**kw)
            except self.openai.BadRequestError as e:
                text = str(e.message).lower()
                if "reasoning_effort" in kw and ("effort" in text or "reasoning" in text):
                    self.send_effort = False
                    kw.pop("reasoning_effort")
                    self._warn_once("effort", "%s: provider rejected reasoning_effort (%s); continuing without",
                                    self.agent.name, e.message)
                elif self.keep_reasoning and "reasoning" in text:
                    self.keep_reasoning = False
                    self._strip_reasoning()
                    kw["messages"] = [{"role": "system", "content": self.system}] + self.messages
                    self._warn_once("reasoning", "%s: provider rejected reasoning in history (%s); stripping it",
                                    self.agent.name, e.message)
                else:
                    raise
        return await self.client.chat.completions.create(**kw)

    async def turn(self, prompt: str) -> TurnStats:
        stats = TurnStats()
        if not self.messages:
            prompt = "(new conversation; your notes carry over what you knew)\n" + prompt
        self.messages.append({"role": "user", "content": prompt})
        rates = await self._rates()
        last_input = 0
        for _ in range(self.max_steps):
            try:
                resp = await self._create()
            except self.openai.RateLimitError:
                stats.error = "rate limited"
                break
            except self.openai.APIStatusError as e:
                stats.error = f"api error {e.status_code}: {e.message}"
                break
            except self.openai.APIConnectionError:
                stats.error = "api connection error"
                break
            u = resp.usage
            if u:
                last_input = u.prompt_tokens or 0
                stats.input_tokens += last_input
                stats.output_tokens += u.completion_tokens or 0
            cost = _usage_cost(u, rates)
            if cost is None:
                self._warn_once("cost", "%s: no price for %s; cost shows as $0", self.agent.name, self.agent.cfg.model)
                cost = 0.0
            stats.cost_usd += cost
            if not resp.choices:
                stats.error = "empty response"
                break
            choice = resp.choices[0]
            msg = choice.message
            # Keep the message as the provider sent it, so reasoning fields round-trip if the provider needs them.
            kept = msg.model_dump(exclude_none=True)
            for k in ("refusal", "annotations", "audio", "function_call"):
                kept.pop(k, None)
            if not self.keep_reasoning:
                kept = {k: v for k, v in kept.items() if not k.startswith("reasoning")}
            kept["role"] = "assistant"
            kept.setdefault("content", "")
            self.messages.append(kept)
            if msg.content and msg.content.strip():
                self.agent.log_thought(msg.content)
            calls = msg.tool_calls or []
            if not calls:
                if choice.finish_reason == "length":
                    stats.error = "output cut off (max_tokens)"
                break
            for tc in calls:
                stats.steps += 1
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as e:
                    out = f"bad arguments for {name}: could not parse them as a JSON object ({e}); call it again"
                else:
                    out = await run_tool(self.agent, name, args)
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        if last_input > self.RESET_AT_INPUT_TOKENS:
            log.info("%s: context at %d tokens, starting a fresh conversation", self.agent.name, last_input)
            self.messages = []
        return stats


def make_backend(agent: "Agent", system: str, workdir: Path, tools=None, max_steps: int = MAX_STEPS_PER_TURN):
    if agent.cfg.backend == "api":
        return ApiBackend(agent, system, workdir, tools, max_steps)
    if agent.cfg.backend in ("openai", "openai-compatible", "gateway"):
        return OpenAIBackend(agent, system, workdir, tools, max_steps)
    if agent.cfg.backend in ("claude-code", "claude_code", "subscription"):
        return ClaudeCodeBackend(agent, system, workdir, tools, max_steps)
    raise ValueError(f"unknown backend {agent.cfg.backend!r} (use claude-code, api or openai)")
