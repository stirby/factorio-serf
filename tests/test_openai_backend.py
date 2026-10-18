"""OpenAIBackend tool loop, bad tool arguments, reasoning round-trip and cost math, against a fake client.

No network, no game. Run: .venv/bin/python tests/test_openai_backend.py
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openai  # noqa: E402
from openai.types.chat import ChatCompletion  # noqa: E402

from crew import backends  # noqa: E402
from crew.config import AgentConfig  # noqa: E402
from crew.tools import BY_NAME, Tool, _obj  # noqa: E402

PRICING = {"deepseek/test": {"input": "0.000001", "output": "0.000002", "input_cache_read": "0.0000001"},
           "deepseek/regional": {"input": "0.000001", "output": "0.000002",
                                 "regional": {"us": {"input": "0.000003", "output": "0.000004"}},
                                 "peak_pricing": {"multiplier": 2, "windows": [{"start_minute_utc": 0,
                                                                                 "end_minute_utc": 1440}]}},
           "deepseek/peak": {"input": "0.000001", "output": "0.000002",
                             "peak_pricing": {"multiplier": 2, "windows": [{"start_minute_utc": 0,
                                                                             "end_minute_utc": 1440}]}}}


def completion(content=None, calls=None, prompt=1000, cached=0, out=100, finish=None, reasoning=None, cost=None):
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    if calls:
        msg["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                              "function": {"name": n, "arguments": a}} for i, (n, a) in enumerate(calls)]
    usage = {"prompt_tokens": prompt, "completion_tokens": out, "total_tokens": prompt + out,
             "prompt_tokens_details": {"cached_tokens": cached}}
    if cost is not None:
        usage["cost"] = cost
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish or ("tool_calls" if calls else "stop")}],
        "usage": usage})


class FakeClient:
    def __init__(self, script, reject=()):
        self.script, self.requests, self.reject = list(script), [], set(reject)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._models)

    async def _models(self):
        return SimpleNamespace(data=[SimpleNamespace(id=k, model_extra={"pricing": v}) for k, v in PRICING.items()])

    async def _create(self, **kw):
        if "effort" in self.reject and "reasoning_effort" in kw:
            raise _bad("reasoning_effort is not supported for this model")
        if "reasoning" in self.reject and any("reasoning_content" in m for m in kw["messages"]):
            raise _bad("unknown field reasoning_content in messages")
        self.requests.append(json.loads(json.dumps(kw, default=str)))
        return self.script.pop(0)

    async def close(self):
        pass


def _bad(text):
    req = SimpleNamespace(method="POST", url="https://x/v1/chat/completions", headers={})
    resp = SimpleNamespace(status_code=400, headers={}, request=req, text=text, json=lambda: {})
    return openai.BadRequestError(text, response=resp, body=None)


class StubAgent:
    def __init__(self, model="deepseek/test", effort=None):
        self.name = "claude-9"
        self.cfg = AgentConfig(name="claude-9", backend="openai", model=model, effort=effort,
                               base_url="https://ai-gateway.vercel.sh/v1")
        self.thoughts, self.tool_log = [], []
        self.pending_jobs, self.finished = set(), {}

    def log_tool(self, name, args):
        self.tool_log.append((name, args))

    def log_tool_result(self, name, out):
        pass

    def log_thought(self, text):
        self.thoughts.append(text)

    def drain_interrupts(self):
        return ""


async def _add(agent, a):
    return str(int(a["a"]) + int(a["b"]))

ADD = Tool("add_test", "add two numbers", _obj({"a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"]), _add)
BY_NAME["add_test"] = ADD


def make(script, model="deepseek/test", effort=None, reject=()):
    os.environ.setdefault("AI_GATEWAY_API_KEY", "test-key")
    agent = StubAgent(model, effort)
    be = backends.OpenAIBackend(agent, "system prompt", Path("/tmp"), [ADD])
    be.client = FakeClient(script, reject)
    backends._PRICES.clear()
    return agent, be


async def main():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok &= bool(cond)

    # two-step tool loop + bad JSON arguments, with reasoning kept in history
    agent, be = make([
        completion(calls=[("add_test", '{"a": 2, "b": 3}'), ("add_test", "{not json")], reasoning="think 1",
                   prompt=1000, cached=400, out=50),
        completion(calls=[("add_test", '{"a": 5, "b": 1}')], prompt=1200, out=40),
        completion(content="It's 6.", prompt=1300, cached=1000, out=10),
    ], effort="high")
    st = await be.turn("what is 2+3+1?")
    req = be.client.requests
    check("three requests, three tool calls", len(req) == 3 and st.steps == 3)
    tool_msgs = [m for m in req[1]["messages"] if m["role"] == "tool"]
    check("first tool result returned", tool_msgs[0]["content"] == "5" and tool_msgs[0]["tool_call_id"] == "call_0")
    check("bad JSON answered, not crashed", "could not parse" in tool_msgs[1]["content"])
    check("reasoning round-trips in history", req[1]["messages"][2].get("reasoning_content") == "think 1")
    check("system prompt first", req[0]["messages"][0] == {"role": "system", "content": "system prompt"})
    check("tools in function format", req[0]["tools"][0]["function"]["name"] == "add_test")
    check("reasoning_effort sent", req[0].get("reasoning_effort") == "high")
    check("final text logged", agent.thoughts == ["It's 6."])
    expect = ((600 * 1e-6 + 400 * 1e-7 + 50 * 2e-6) + (1200 * 1e-6 + 40 * 2e-6) + (300 * 1e-6 + 1000 * 1e-7 + 10 * 2e-6))
    check(f"cost from price list ({st.cost_usd:.6f} vs {expect:.6f})", abs(st.cost_usd - expect) < 1e-9)
    check("token totals", st.input_tokens == 3500 and st.output_tokens == 100 and st.error is None)

    # provider rejects reasoning_effort, then reasoning fields in history: both dropped, turn still works
    agent, be = make([completion(calls=[("add_test", '{"a": 1, "b": 1}')], reasoning="r"),
                      completion(content="2")], effort="high", reject=("effort", "reasoning"))
    st = await be.turn("1+1?")
    check("effort dropped after rejection", not be.send_effort and "reasoning_effort" not in be.client.requests[-1])
    check("reasoning stripped after rejection", not be.keep_reasoning
          and all("reasoning_content" not in m for m in be.client.requests[-1]["messages"]))
    check("turn completed despite rejections", st.error is None and agent.thoughts == ["2"])

    # provider-reported cost wins; regional US prices win over peak-adjusted defaults
    agent, be = make([completion(content="hi", cost=0.0123)])
    st = await be.turn("hi")
    check("provider-reported cost used", abs(st.cost_usd - 0.0123) < 1e-12)
    r = backends._rates(PRICING["deepseek/regional"])
    check("US regional rates preferred, no peak multiplier", r["input"] == 3e-6 and r["output"] == 4e-6)
    r = backends._rates(PRICING["deepseek/peak"], now=time.time())
    check("peak window doubles default rates", r["input"] == 2e-6 and r["cache_read"] == 2e-6)
    agent, be = make([completion(content="x")], model="unknown/model")
    st = await be.turn("x")
    check("unknown price -> $0, no crash", st.cost_usd == 0 and st.error is None)

    # context reset above the threshold
    agent, be = make([completion(content="big", prompt=200_000)])
    await be.turn("x")
    check("history reset after a huge context", be.messages == [])
    print("ALL PASS" if ok else "SOME FAILED")
    return ok


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
