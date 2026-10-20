"""Chat settings commands: "@serf model opus", "@serf fast on". The app handles them; the model never sees them.

    .venv/bin/python tests/test_chat_commands.py
"""
import asyncio
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crew.config import AgentConfig  # noqa: E402
from crew.orchestrator import Orchestrator  # noqa: E402
from crew.router import parse_command, resolve_model, route  # noqa: E402


class FakeAgent:
    """Just what _settings_command touches; apply() mirrors Agent.apply for model and fast."""

    def __init__(self, cfg, owner="otterplex"):
        self.name, self.owner, self.cfg = cfg.name, owner, cfg
        self.said, self.heard, self.backend_calls = [], [], []

    async def say(self, text):
        self.said.append(text)

    def hear(self, line, wake, urgent=True):
        self.heard.append((line, wake))

    async def apply(self, cfg):
        changed = []
        if cfg.model != self.cfg.model:
            self.backend_calls.append(("set_model", cfg.model))
            changed.append("model")
        if cfg.fast != self.cfg.fast:
            self.backend_calls.append(("set_fast", cfg.fast))
            changed.append("fast")
        self.cfg = cfg
        return changed


def test_parse():
    assert parse_command("model opus") == ("model", "opus")
    assert parse_command("Model claude-opus-5-5!") == ("model", "claude-opus-5-5")
    assert parse_command("model") == ("model", "")
    assert parse_command("fast on") == ("fast", "on")
    assert parse_command("fast mode off") == ("fast", "off")
    assert parse_command("fast") == ("fast", "")
    # orders that merely contain the words stay orders
    assert parse_command("model a train station for me") is None
    assert parse_command("fast, build the smelters") is None
    assert parse_command("use opus") is None
    assert resolve_model("opus") == "claude-opus-5-5"
    assert resolve_model("claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert resolve_model("deepseek/deepseek-v4-pro") == "deepseek/deepseek-v4-pro"
    assert resolve_model("gpt") is None
    r = route("@serf model sonnet", ["serf"], None)
    assert r.targets == {"serf"} and r.command == ("model", "sonnet")
    assert route("model sonnet", ["serf"], None).command is None  # not addressed to anyone


async def run(agent, player, text):
    cmd = parse_command(text)
    assert cmd, text
    await Orchestrator._settings_command(None, agent, player, *cmd)


async def test_commands():
    a = FakeAgent(AgentConfig(name="serf", model="claude-sonnet-5-5"))

    await run(a, "otterplex", "fast on")  # Sonnet has no fast mode
    assert not a.cfg.fast and not a.backend_calls and "only works on Opus" in a.said[-1]

    await run(a, "otterplex", "model opus")
    assert a.cfg.model == "claude-opus-5-5" and a.backend_calls == [("set_model", "claude-opus-5-5")]
    assert a.said[-1].startswith("Now on Opus 5.5") and a.heard[-1][1] is False  # told, not woken

    await run(a, "otterplex", "fast on")
    assert a.cfg.fast and a.backend_calls[-1] == ("set_fast", True) and "Opus 5.5 fast" in a.said[-1]

    await run(a, "otterplex", "model haiku")  # leaving Opus turns fast mode off with it
    assert a.cfg.model == "claude-haiku-5-5" and not a.cfg.fast
    assert a.backend_calls[-2:] == [("set_model", "claude-haiku-5-5"), ("set_fast", False)]
    assert "only works on Opus" in a.said[-1]

    n = len(a.backend_calls)
    await run(a, "otterplex", "model gpt")
    await run(a, "someone-else", "model opus")
    await run(a, "otterplex", "model")
    assert len(a.backend_calls) == n and a.cfg.model == "claude-haiku-5-5"
    assert "don't know" in a.said[-3] and "Only otterplex" in a.said[-2] and "I'm on Haiku 5.5" in a.said[-1]

    o = FakeAgent(dataclasses.replace(a.cfg, backend="openai", model="deepseek/deepseek-v4-pro"))
    await run(o, "otterplex", "model deepseek/deepseek-v4-flash")
    assert o.cfg.model == "deepseek/deepseek-v4-flash"
    await run(o, "otterplex", "fast on")
    assert not o.cfg.fast and "only works with Claude" in o.said[-1]


class FakeLink:
    client = "p1"

    async def call(self, op, **kw):
        assert op == "list"
        return {"agents": []}


class FakeOrch:
    """What _serf_add touches; _add_agent records the config the serf would start with."""

    def __init__(self):
        from crew.config import CrewConfig
        self.cfg = CrewConfig()
        self.cfg.defaults = {"model": "claude-opus-5-5", "fast": True}
        self.link, self.world_owners, self.added, self.told = FakeLink(), set(), [], []

    async def _add_agent(self, ac):
        self.added.append(ac)
        return ac

    async def _greet(self, agent):
        pass

    async def _tell(self, player, text):
        self.told.append(text)


async def test_add_with_model():
    o = FakeOrch()
    await Orchestrator._serf_add(o, {"type": "add", "player": "otterplex", "name": "sonnet"})
    ac = o.added[-1]
    assert ac.name == o.cfg.kind and ac.model == "claude-sonnet-5-5" and not ac.fast  # a model, not a name

    await Orchestrator._serf_add(o, {"type": "add", "player": "otterplex", "name": "bob"})
    assert o.added[-1].name == "bob" and o.added[-1].model == "claude-opus-5-5" and o.added[-1].fast

    await Orchestrator._serf_add(o, {"type": "add", "player": "otterplex"})
    assert o.added[-1].name == o.cfg.kind and o.added[-1].model == "claude-opus-5-5"


if __name__ == "__main__":
    test_parse()
    asyncio.run(test_commands())
    asyncio.run(test_add_with_model())
    print("ok")
