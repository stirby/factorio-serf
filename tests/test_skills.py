"""The serf's own library: saving, the safe script subset, running scripts against (fake) tools. No game, no model.

  .venv/bin/python tests/test_skills.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SERF_SKILLS_DIR"] = tempfile.mkdtemp(prefix="serf-skills-")

from crew import skills, tools as T  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


def rejected(code: str) -> str:
    return skills.save("bad_one", "script", "x", code=code)


async def main() -> None:
    # The subset: no way out to the host.
    for code, why in [("import os", "import"), ("open('/etc/passwd')", "open"), ("x = ().__class__", "dunder"),
                      ("'{0.__class__}'.format(1)", "str.format"), ("def f():\n  pass", "def"),
                      ("f = lambda: 1", "lambda"), ("try:\n  x = 1\nexcept Exception:\n  pass", "try"),
                      ("g = (i for i in [1])\nf = g.gi_frame", "frame"), ("x = 2 ** 10 ** 9", "big power"),
                      ("_x = 1", "underscore name")]:
        msg = rejected(code)
        if why == "open":  # parses fine; there's simply no open() at run time
            check(not msg.startswith("error"), "open() parses (it just doesn't exist when run)")
            continue
        check(msg.startswith("error"), f"rejects {why}: {msg}")

    calls: list[tuple[str, dict]] = []

    def fake(name, reply):
        async def h(agent, a):
            calls.append((name, a))
            return reply(a) if callable(reply) else reply
        return SimpleNamespace(handler=h)

    T.BY_NAME = dict(T.BY_NAME)
    T.BY_NAME["inspect"] = fake("inspect", lambda a: json.dumps({"entities": [{"n": "stone-furnace", "p": [a["x"], a["y"]]}]}))
    T.BY_NAME["act"] = fake("act", lambda a: "#1 place: OK placed " + a["actions"][0]["name"])
    T.BY_NAME["wait"] = fake("wait", "nothing")
    agent = SimpleNamespace(name="serf", interrupted=asyncio.Event(), pending_jobs=set(),
                            orch=SimpleNamespace(cfg=SimpleNamespace(state_dir=Path("/tmp/x"))))

    code = """found = []
for i in range(n):
    r = parse(inspect(x=x0 + 2 * i, y=y0, radius=1))
    found.append(r["entities"][0]["n"])
r = act([{"op": "place", "name": "inserter", "x": x0, "y": y0 - 1}])
if failed(r):
    return "placing failed: " + r
log(f"saw {len(found)}")
return f"{len(found)} furnaces, inserter placed"
"""
    msg = skills.save("check_row", "script", "inspect a furnace row and add an inserter", code=code,
                      params=["x0", "y0", "n"], author="serf")
    check(msg == "script check_row saved", f"a good script saves: {msg}")
    ok, out = await skills.run(agent, "check_row", {"x0": 10, "y0": 5, "n": 3})
    check(ok and "3 furnaces, inserter placed" in out and "saw 3" in out, f"script runs against the tools: {out[:160]}")
    check([c[0] for c in calls] == ["inspect"] * 3 + ["act"], f"tool calls in order: {[c[0] for c in calls]}")

    skills.save("spin", "script", "loops forever", code="while True:\n    x = 1")
    ok, out = await skills.run(agent, "spin", {})
    check(not ok and "loop ran over" in out, f"a runaway loop stops: {out[:120]}")

    skills.save("boom", "script", "divides by zero", code="return 1 / 0")
    ok, out = await skills.run(agent, "boom", {})
    check(not ok and "ZeroDivisionError" in out, f"a crash is reported, not raised: {out[:120]}")

    skills.save("outer", "script", "calls another script", code="return skill(name='check_row', x0=0, y0=0, n=1)")
    ok, out = await skills.run(agent, "outer", {})
    check(ok and "1 furnaces" in out, f"scripts can call scripts: {out[:160]}")

    agent.interrupted.set()
    ok, out = await skills.run(agent, "check_row", {"x0": 1, "y0": 1, "n": 1})
    check(not ok and "a human said something" in out, f"a human speaking stops a script: {out[:100]}")
    agent.interrupted.clear()

    skills.save("smelt_how", "playbook", "how to feed a furnace row", text="Ore belt on top, inserters down.")
    idx = skills.render_index()
    check("check_row(x0, y0, n) script" in idx and "[2/3 ok]" in idx and "smelt_how playbook" in idx,
          f"the index shows params, success rate, playbooks:\n{idx}")
    v2 = skills.save("check_row", "script", "v2", code="return 'v2'", params=[])
    check("v2" in v2, f"same name = new version: {v2}")

    os.environ["SERF_LIBRARY_FROZEN"] = "1"
    check(skills.save("nope", "playbook", "x", text="y").startswith("error"), "a frozen library refuses saves")
    del os.environ["SERF_LIBRARY_FROZEN"]
    check("noted" in skills.friction("connect never says which way the last belt faces", "serf", "run1"),
          "friction is logged")
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
