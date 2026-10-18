"""Foreman queue/answer plumbing with a scripted model: no game, no LLM.

Run: .venv/bin/python tests/test_foreman.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crew import foreman as fm_mod  # noqa: E402
from crew.board import Board  # noqa: E402
from crew.config import AgentConfig  # noqa: E402
from crew.tools import run_tool  # noqa: E402


class FakeWorker:
    def __init__(self, name):
        self.name = name
        self.heard = []
        self.mode, self.in_turn, self.idle_since, self.status_text = "working", True, 0, "building"
        self.cfg = AgentConfig(name=name, focus="resources")

    def hear(self, line, wake, urgent=True):
        self.heard.append(line)


class FakeLink:
    async def call(self, op, **kw):
        if op == "vitals":
            return {"research": "steel", "progress": 50, "labs": 4, "labs_working": 4, "plates": {"iron": 300}}
        return {}


class ScriptedBackend:
    """Each turn runs the next script against the foreman, the way the model would call tools."""

    def __init__(self, fm, scripts):
        self.fm, self.scripts, self.prompts = fm, scripts, []

    async def start(self):
        pass

    async def close(self):
        pass

    async def reset(self):
        pass

    async def turn(self, prompt):
        self.prompts.append(prompt)
        script = self.scripts.pop(0) if self.scripts else None
        if script:
            await script(self.fm)
        return SimpleNamespace(cost_usd=0.01, steps=1, input_tokens=1000, error=None)


async def main():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok &= bool(cond)

    tmp = Path(tempfile.mkdtemp())
    said = []
    w1, w2 = FakeWorker("claude-1"), FakeWorker("claude-2")

    async def announce(speaker, text):
        said.append(text)
    orch = SimpleNamespace(cfg=SimpleNamespace(state_dir=tmp, agents=[w1.cfg, w2.cfg], flag=lambda *a: True),
                           board=Board(tmp / "board.json"), link=FakeLink(),
                           agents={"claude-1": w1, "claude-2": w2}, announce=announce)
    orch.foreman_brain = None

    gate = asyncio.Event()

    async def first(fm):
        await gate.wait()  # claude-2 asks while this turn is running
        out = await run_tool(fm, "reply", {"to": "claude-1", "text": "build copper at 10,20", "q": [1]})
        assert "sent" in out
        fm._mid = out

    async def second(fm):
        await run_tool(fm, "reply", {"to": "chat", "text": "on it"})
        fm.log_thought("closing words")

    real = fm_mod.make_backend
    fm_mod.make_backend = lambda agent, *a, **k: ScriptedBackend(agent, [first, second])
    try:
        fm = fm_mod.Foreman(AgentConfig(name="foreman", max_turns_per_hour=10), orch)
    finally:
        fm_mod.make_backend = real
    orch.foreman_brain = fm
    fm_mod.BATCH_WAIT = 0
    await fm.start()

    q1 = fm.ask("claude-1", "where should copper go?")
    await asyncio.sleep(0.05)
    check("turn started on a question", fm.in_turn)
    q2 = fm.ask("claude-2", "can I take the steel row?")
    fm.human("otterplex", "@foreman get blue science going")
    gate.set()
    await asyncio.sleep(0.2)
    check("claude-1 got its answer", any("build copper at 10,20" in h for h in w1.heard))
    check("mid-turn arrivals shown in the same turn", "Q#2" in getattr(fm, "_mid", "") and "otterplex" in fm._mid)
    check("chat reply announced", said == ["on it"])
    check("unanswered Q#2 got the closing words", any(f"Q#{q2}" in h and "closing words" in h for h in w2.heard))
    check("no duplicate answer to claude-1", sum("Q#" in h for h in w1.heard) == 0)
    check("briefing has the [base] line", "[base] researching steel" in fm.backend.prompts[0])
    check("question ids increase", (q1, q2) == (1, 2))
    await fm.close()

    # Batching: questions arriving within the window share one turn.
    fm_mod.BATCH_WAIT = 0.5
    seen = []

    async def answer_all(f):
        seen.append(len(f.open_q))
        for q in list(f.open_q.values()):
            await run_tool(f, "reply", {"to": q["from"], "text": "ok", "q": [q["id"]]})
    fm_mod.make_backend = lambda agent, *a, **k: ScriptedBackend(agent, [answer_all, answer_all])
    try:
        fm2 = fm_mod.Foreman(AgentConfig(name="foreman", max_turns_per_hour=10), orch)
    finally:
        fm_mod.make_backend = real
    orch.foreman_brain = fm2
    await fm2.start()
    fm2.ask("claude-1", "a?")
    await asyncio.sleep(0.2)
    fm2.ask("claude-2", "b?")
    await asyncio.sleep(1.0)
    check("two questions in the window -> one turn", seen == [2])
    fm2.human("otterplex", "@foreman hi")
    await asyncio.sleep(0.2)
    check("human message skips the batching wait", len(seen) == 2)
    await fm2.close()
    print("ALL PASS" if ok else "SOME FAILED")
    return ok


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
