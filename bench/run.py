#!/usr/bin/env python3
"""One scored run of the Jev+Opus agent on a scenario, on an isolated server instance. Same scenarios, scoring and
player behaviour as the serf's bench (tests/bench.py in factorio-serf), so results compare directly.

    .venv/bin/python bench/run.py --scenario bench/scenarios/t-starved.json --instance 53 [--no-think] [--minutes N]

Flow: start the instance from the stage -> setup_lua -> spawn the agent -> objectives one at a time ("ops" says the
goal; met = checks hold for hold_samples one-minute samples) -> result.json in bench/runs/<run_id>/ with time to
each objective, Jev calls/cost/latency, thinker turns/cost/secs, character idle share and the actor's metrics.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.rcon import GameError, RconError  # noqa: E402
from jev.typesafe import Jev  # noqa: E402

PRELUDE = (ROOT / "bench" / "prelude.lua").read_text()
RUNS = ROOT / "bench" / "runs"
RESULTS = ROOT / "bench" / "results.jsonl"


def chunk(lua: str) -> str:
    return PRELUDE + (lua if re.search(r"\breturn\b", lua) else f"return ({lua})")


def jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")


class Scorer:
    """Copied from the serf bench: checks are Lua expressions; rate checks score their increase per game minute."""

    def __init__(self, game: Game, checks: list[dict]):
        self.g, self.checks = game, checks
        self.prev: dict = {}
        self.baseline: dict = {}
        self.targets = {c["name"]: c.get("target") for c in checks}
        self.reached: dict = {}

    async def eval(self, lua: str):
        return (await asyncio.wait_for(self.g.call("eval", code=chunk(lua)), 30)).get("result")

    async def sample(self) -> dict:
        tick = await self.eval("game.tick")
        out = {"tick": tick, "values": {}, "errors": {}}
        for c in self.checks:
            try:
                v = await self.eval(c["lua"])
                v = float(v) if isinstance(v, (int, float)) else (float(bool(v)) if isinstance(v, bool) else v)
            except (GameError, RconError, asyncio.TimeoutError) as e:
                out["errors"][c["name"]] = str(e)[:300]
                v = None
            if c.get("rate") and isinstance(v, float):
                raw = v
                hist = self.prev.setdefault(c["name"], [])
                hist.append((raw, tick))
                base = None
                for r0, t0 in reversed(hist[:-1]):
                    base = (r0, t0)
                    if tick - t0 >= 3600:
                        break
                del hist[:-12]
                v = None if not base or tick <= base[1] else max(0.0, raw - base[0]) / ((tick - base[1]) / 3600)
            out["values"][c["name"]] = v
        return out

    def set_baseline(self, s: dict) -> None:
        self.baseline = dict(s["values"])
        for c in self.checks:
            m = c.get("target_mult_baseline")
            if m is not None:
                b = self.baseline.get(c["name"]) or 0.0
                self.targets[c["name"]] = round(m * b, 3) if b > 0 else c.get("target")
            if c.get("target_delta") is not None:
                self.targets[c["name"]] = float((self.baseline.get(c["name"]) or 0.0) + c["target_delta"])

    def met(self, s: dict, elapsed: float) -> bool:
        ok, any_t = True, False
        for n, v in s["values"].items():
            t = self.targets.get(n)
            if t is None:
                continue
            any_t = True
            if isinstance(v, float) and v >= t:
                self.reached.setdefault(n, round(elapsed, 1))
            else:
                ok = False
        return any_t and ok

    def short(self, s: dict) -> str:
        out = []
        for n, v in s["values"].items():
            t = self.targets.get(n)
            if t is not None and isinstance(v, float) and v < t:
                out.append(f"{n.replace('_', ' ')} is {v:,.0f}, needs {t:,.0f}")
        return "; ".join(out)


async def run(a) -> dict:
    scn = json.loads(Path(a.scenario).read_text())
    run_id = a.run_id or time.strftime("%Y%m%d-%H%M%S") + f"-{scn['name']}-{a.tag}"
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "scenario.json").write_text(json.dumps(scn, indent=1))
    minutes = float(a.minutes or scn.get("minutes", 10))
    from jev.library import lessons
    res: dict = {"run_id": run_id, "scenario": scn["name"], "tag": a.tag, "think": not a.no_think,
                 "lessons_at_start": len(lessons()),
                 "start": time.strftime("%Y-%m-%d %H:%M:%S"), "minutes_planned": minutes, "errors": [],
                 "objectives": []}
    inst = Instance(a.instance, scn["stage"])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    if inst.running():  # a leftover from a run that died: our instance numbers are ours
        await asyncio.to_thread(inst.stop)
    await asyncio.to_thread(inst.start, 240)
    actor = None
    jev = Jev(log_path=d / "jev.jsonl")
    try:
        g = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")
        sg = await Game.connect(inst.host, inst.rcon_port, inst.password, "serf")  # scorer's own connection
        for x in (await g.call("list"))["agents"]:
            try:
                await g.call("cancel", agent=x["name"], reason="bench reset")
            except GameError:
                pass
        setup = {}
        if scn.get("setup_lua"):
            setup = (await asyncio.wait_for(g.call("eval", code=chunk(scn["setup_lua"]), timeout=60), 70)).get("result")
        res["setup"] = setup
        await g.start()
        actor = Actor(g, jev, d, "serf", think=not a.no_think, thinker_effort=a.effort)
        await actor.start()
        # the player answers questions the agent asks during an objective
        answer = {"text": None, "n": 0}
        orig_say = actor.say

        async def say(text):
            await orig_say(text)
            if "?" in text and answer["text"] and answer["n"] < 3:
                answer["n"] += 1
                await g.call("chat", player="ops", message=answer["text"])
        actor.say = say
        list0 = {x["name"]: x for x in (await g.call("list"))["agents"]}
        t0 = time.time()
        res["t0"] = t0
        deadline = t0 + minutes * 60
        for ob in scn.get("objectives") or []:
            if stop.is_set() or time.time() >= deadline - 30:
                res["objectives"].append({"name": ob["name"], "skipped": True})
                continue
            sc = Scorer(sg, ob["score"])
            sc.set_baseline(await sc.sample())
            goal = fill(ob["goal"], setup)
            answer["text"], answer["n"] = fill("@{agent} " + (ob.get("answer") or "Your call."), setup), 0
            ts = time.time()
            await g.call("chat", player="ops", message=goal)
            jsonl(d / "timeline.jsonl", {"t": ts, "event": "objective", "name": ob["name"], "text": goal})
            print(f"bench: objective {ob['name']}: {goal}", flush=True)
            limit = min(ts + ob.get("minutes", 30) * 60, deadline)
            held, need, ok, smp = 0, ob.get("hold_samples", 2), False, None
            next_sample, nudged = ts + 60, 0.0
            idle_since = None
            while time.time() < limit and not stop.is_set():
                now = time.time()
                busy = any(o.status in ("new", "working", "thinking") for o in actor.orders)
                idle_since = None if busy else (idle_since or now)
                if now >= next_sample:
                    next_sample += 60
                    try:
                        smp = await sc.sample()
                    except Exception as e:  # noqa: BLE001
                        res["errors"].append(f"sample: {e!r}")
                        continue
                    jsonl(d / "timeline.jsonl", {"t": now, "elapsed": round(now - t0, 1), "objective": ob["name"], **smp})
                    print(f"bench: {round((now - t0) / 60, 1)} min [{ob['name']}]: {smp['values']}", flush=True)
                    held = held + 1 if sc.met(smp, now - ts) else 0
                    if held >= need:
                        ok = True
                        break
                    if idle_since and now - idle_since > 45 and now - nudged > 180:
                        nudged = now
                        short = sc.short(smp)
                        await g.call("chat", player="ops", message=f"@serf not done yet: {short}. Keep going on it."
                                     if short else "@serf not done yet: it has to hold for a few minutes. Keep at it.")
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except asyncio.TimeoutError:
                    pass
            secs = round(time.time() - ts, 1)
            res["objectives"].append({"name": ob["name"], "success": ok, "secs": secs,
                                      "values": (smp or {}).get("values"), "targets": sc.targets})
            print(f"bench: objective {ob['name']}: {'MET' if ok else 'not met'} in {secs / 60:.1f} min", flush=True)
            await g.call("chat", player="ops", message="@serf thanks, that one's done." if ok
                         else "@serf let's leave that one for now.")
            await asyncio.sleep(2)
        res["elapsed_s"] = round(time.time() - t0, 1)
        list1 = {x["name"]: x for x in (await g.call("list"))["agents"]}
        s0, s1 = (list0.get("serf") or {}).get("stats") or {}, (list1.get("serf") or {}).get("stats") or {}
        if isinstance(s1, dict) and s1:
            dd = {k: s1.get(k, 0) - (s0.get(k, 0) if isinstance(s0, dict) else 0) for k in ("busy_ticks", "idle_ticks")}
            tot = dd["busy_ticks"] + dd["idle_ticks"]
            res["char_idle_pct"] = round(100 * dd["idle_ticks"] / tot, 1) if tot else None
    except Exception as e:  # noqa: BLE001
        import traceback
        res["errors"].append(f"run: {e!r}")
        traceback.print_exc()
    finally:
        if actor:
            res["actor"] = actor.metrics
            if actor.thinker:
                st = actor.thinker.stats
                res["thinker"] = {"turns": st.turns, "cost_usd": round(st.cost_usd, 4), "secs": round(st.secs, 1),
                                  "tool_calls": st.tool_calls, "errors": st.errors, "usage_limited": st.usage_limited}
            try:
                await asyncio.wait_for(actor.stop(), 30)
            except BaseException:  # noqa: BLE001
                pass
        res["jev"] = jev.stats.as_dict()
        await jev.close()
        await asyncio.to_thread(inst.stop)
        obs = res["objectives"]
        res["success"] = bool(obs) and all(o.get("success") for o in obs)
        res["met"] = sum(1 for o in obs if o.get("success"))
        res["cost_usd"] = round((res.get("thinker") or {}).get("cost_usd", 0) + res["jev"]["cost_usd"], 4)
        res["end"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (d / "result.json").write_text(json.dumps(res, indent=1, default=str))
        line = {k: res.get(k) for k in ("run_id", "scenario", "tag", "think", "success", "met", "elapsed_s", "cost_usd",
                                        "char_idle_pct")}
        line["objectives"] = [{k: o.get(k) for k in ("name", "success", "secs")} for o in obs]
        line["thinker"] = res.get("thinker")
        line["jev"] = {k: res["jev"].get(k) for k in ("calls", "cost_usd", "ms_mean")}
        line["actor"] = res.get("actor")
        line["errors"] = res["errors"][:5]
        if not a.no_record:
            jsonl(RESULTS, line)
        print(json.dumps(line, default=str), flush=True)
    return res


def fill(text: str, setup) -> str:
    text = text.replace("{agent}", "serf")
    if isinstance(setup, dict):
        text = re.sub(r"\{(\w+)\}", lambda m: str(setup.get(m.group(1), m.group(0))), text)
    return text


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", required=True)
    p.add_argument("--instance", type=int, default=53)
    p.add_argument("--minutes", type=float)
    p.add_argument("--tag", default="duo")
    p.add_argument("--run-id")
    p.add_argument("--no-think", action="store_true", help="no Opus: Jev + code only")
    p.add_argument("--effort", default=None, help="thinker effort (low/medium/high)")
    p.add_argument("--no-record", action="store_true")
    a = p.parse_args()
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
