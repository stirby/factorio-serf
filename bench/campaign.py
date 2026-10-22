#!/usr/bin/env python3
"""A campaign: how far the serf gets into the game with an Opus "player" (bench/strategist.py) giving it orders, in
generations. Each generation runs for some hours from a save: the previous generation's last save, or a fresh world
(scripts/new_world.py) when the previous one spent most of its time fixing without getting further. Progress is
probed every few minutes (jev/progress.py), the world is saved every half hour, and each generation ends with a
summary. Lessons and designs the planner saves go to the campaign's own library, so they carry over.

    .venv/bin/python bench/campaign.py --name c1 --world campaign-w1 --gen-hours 3 --gens 8 --instance 75
Files: bench/campaigns/<name>/ (campaign.json, gen-NN/{actor,jev,thinker,strategist,progress}, saves/)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "bench"))
from instance import INSTALL, Instance  # noqa: E402

from jev import progress  # noqa: E402
from jev.game import Game, GameError  # noqa: E402
from jev.typesafe import reader  # noqa: E402

GOAL = ("launch a rocket from Nauvis. On the way: automate red, green, blue, purple and yellow science, research "
        "the rocket silo, build it and feed it.")
CONFIRM_MIN = 15  # a ladder target counts once it's still being made this many minutes later
MILESTONE_ITEM = {3: "automation-science-pack", 4: "logistic-science-pack", 5: "petroleum-gas",
                  6: "chemical-science-pack", 7: "production-science-pack", 8: "utility-science-pack"}
PROJECT_ORDER = "@serf project: beat the game. Launch a rocket from Nauvis; automate each science pack on the way."


def jsonl(p: Path, rec: dict) -> None:
    with open(p, "a") as f:
        f.write(json.dumps({"t": time.time(), **rec}, default=str) + "\n")


def say(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


class Generation:
    def __init__(self, camp: "Campaign", n: int, stage: str):
        self.camp, self.n, self.stage = camp, n, stage
        self.dir = camp.dir / f"gen-{n:02d}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.probes: list[dict] = []
        self.serf_lines: list[str] = []
        self.orders_sent = 0
        self.reached: float | None = None  # seconds into the generation when the target level was first seen
        self.at_reach: dict | None = None  # the probe that first saw it
        self.sustained: bool | None = None  # still making it CONFIRM_MIN later (not a burst from hand-stocked chests)
        self.bursts: list[float] = []  # minutes at which the target was seen but then not sustained
        self.t0 = time.time()

    async def probe(self, g: Game) -> dict | None:
        try:
            p = await progress.probe(g)
        except Exception as e:  # noqa: BLE001
            jsonl(self.dir / "progress.jsonl", {"error": repr(e)})
            return None
        self.probes.append(p)
        jsonl(self.dir / "progress.jsonl", p)
        if self.camp.target and self.reached is None and self.camp.target_met(p):
            self.reached = time.time() - self.t0
            self.at_reach = p
            say(f"{self.camp.name} g{self.n}: reached milestone {self.camp.target} after {self.reached / 60:.0f} min; "
                f"checking it keeps running for {CONFIRM_MIN} min")
        elif self.at_reach is not None and self.sustained is None and \
                time.time() - self.t0 - self.reached >= CONFIRM_MIN * 60 - 30:
            more = self.camp.target_growth(self.at_reach, p)
            ok = all(v >= CONFIRM_MIN for v in more.values())
            say(f"{self.camp.name} g{self.n}: {'sustained' if ok else 'NOT sustained'} over {CONFIRM_MIN} min: {more}")
            if ok:
                self.sustained = True
            else:
                # a burst, not a running line: keep going (the project carries on) and check again later
                self.bursts.append(round(self.reached / 60, 1))
                self.reached, self.at_reach = None, None
        return p

    async def save(self, g: Game, tag: str) -> Path | None:
        name = f"{self.camp.name}-g{self.n:02d}-{tag}"
        try:
            await g.call("eval", code=f'game.server_save("{name}") return true', timeout=120)
        except Exception as e:  # noqa: BLE001
            say(f"save {name} failed: {e!r}")
            return None
        src = self.inst.dir / "saves" / f"{name}.zip"
        for _ in range(60):
            if src.exists() and src.stat().st_size > 0:
                break
            await asyncio.sleep(1)
        await asyncio.sleep(3)
        if not src.exists():
            return None
        dst = self.camp.dir / "saves" / f"{name}.zip"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    def report(self, last: dict | None, t_left: float) -> str:
        p = self.probes[-1] if self.probes else None
        r = progress.rates(self.probes[-2], p) if len(self.probes) >= 2 else None
        lines = [f"Generation {self.n}, {t_left / 60:.0f} minutes left in it. Orders given this generation: "
                 f"{self.orders_sent}."]
        if p:
            lines.append("State of the world:\n" + progress.summary(p, r))
        if last:
            lines.append(f"Your last order: \"{last['text']}\" -> {last['outcome']} after {last['mins']:.0f} min.")
        if self.serf_lines:
            lines.append("What the serf said lately:\n" + "\n".join(self.serf_lines[-12:]))
        return "\n\n".join(lines)

    async def run(self, hours: float) -> dict:
        from jev.actor import Actor
        from strategist import Strategist
        camp = self.camp
        self.inst = Instance(camp.k, self.stage)
        os.environ["JEV_LIBRARY"] = str(camp.dir / "library")
        pids = subprocess.run(["pgrep", "-f", f"bin/x64/[f]actorio -c {self.inst.dir}/config/"],
                              capture_output=True, text=True).stdout.split()
        for pid in pids:
            subprocess.run(["kill", pid], check=False)
        for attempt in range(5):
            try:
                await asyncio.to_thread(self.inst.start, 300)
                break
            except RuntimeError as e:
                if attempt == 4:
                    raise
                say(f"start retry: {str(e)[:200]}")
                await asyncio.sleep(8)
        if camp.mode == "project":
            os.environ["JEV_PROJECT_DIR"] = str(camp.dir / "project")
        jev = reader(log_path=self.dir / "jev.jsonl")
        g = await Game.connect(self.inst.host, self.inst.rcon_port, self.inst.password, "serf")
        pg = await Game.connect(self.inst.host, self.inst.rcon_port, self.inst.password, "serf")  # probes, saves
        await g.start()
        actor = Actor(g, jev, self.dir, "serf", think=True, thinker_effort=camp.effort)
        actor.project_effort = camp.strategist_effort
        actor.allow_projects = camp.mode == "project"  # the strategist is the project manager in its mode
        await actor.start()
        orig_say = actor.say

        async def say_hook(text):
            await orig_say(text)
            self.serf_lines.append(time.strftime("%H:%M ") + text[:200])
            if text.rstrip().endswith("?"):  # the player answers a question with a shrug, as in the bench
                await g.call("chat", player="boss", message="@serf your call")
        actor.say = say_hook
        strat = Strategist(GOAL, actor._thinker_tools(), camp.dir / "strategist", effort=camp.strategist_effort)
        t0 = self.t0 = time.time()
        deadline = t0 + hours * 3600
        actor.project_deadline = deadline - 120
        stop = asyncio.Event()

        async def keeper():
            next_save = time.time() + 1800
            while not stop.is_set():
                p = await self.probe(pg)
                if p:
                    say(f"{camp.name} g{self.n}: milestone {p['level']} ({', '.join(p['milestones'][-2:])}), "
                        f"{p['techs']} techs, research {p.get('research')}")
                if time.time() >= next_save:
                    await self.save(pg, f"t{int((time.time() - t0) / 60):03d}")
                    next_save += 1800
                try:
                    await asyncio.wait_for(stop.wait(), 120 if camp.target else 300)
                except asyncio.TimeoutError:
                    pass
        ktask = asyncio.create_task(keeper())
        last = None
        try:
            while camp.mode == "project" and time.time() < deadline - 150 and self.sustained is None:
                # one order starts the serf's own project; when a project ends before the time is up (it gave up or
                # crashed), it's started again: its journal carries on
                pr = actor.project
                if pr is not None and pr.status == "done" and self.reached is not None:
                    await asyncio.sleep(20)  # met: only the 15-minute check is left; no need to start it again
                    continue
                if pr is None or not pr.active:
                    if pr is not None:
                        say(f"{camp.name} g{self.n}: project ended {pr.status}: {pr.summary[:160]}")
                        jsonl(self.dir / "campaign.jsonl", {"kind": "project_end", "status": pr.status,
                                                             "summary": pr.summary, "turns": pr.turns,
                                                             "usd": pr.usd})
                        if pr.status == "done" and (self.probes and self.probes[-1].get("rockets")):
                            break
                    text = camp.order if pr is None else "@serf carry on with the project: " + camp.goal
                    say(f"{camp.name} g{self.n} order: {text}")
                    await g.call("chat", player="boss", message=text)
                    self.orders_sent += 1
                    await asyncio.sleep(90)
                    if actor.project is pr:  # the order didn't start one (taken some other way): start it directly
                        actor.start_project(camp.goal, "boss")
                        say(f"{camp.name} g{self.n}: started the project directly")
                    continue
                await asyncio.sleep(20)
            while camp.mode == "strategist" and time.time() < deadline and self.sustained is None:
                when = f"g{self.n} +{int((time.time() - t0) / 60)}m"
                try:
                    d = await strat.decide(self.report(last, deadline - time.time()), when)
                except Exception as e:  # noqa: BLE001
                    say(f"strategist error: {e!r}")
                    jsonl(self.dir / "campaign.jsonl", {"kind": "strategist_error", "error": repr(e)})
                    await asyncio.sleep(60)
                    continue
                jsonl(self.dir / "campaign.jsonl", {"kind": "decision", **d})
                if d.get("order"):
                    text = d["order"] if d["order"].lower().startswith("@serf") else "@serf " + d["order"]
                    say(f"{camp.name} g{self.n} order: {text[:160]}")
                    n_before = len(actor.orders)
                    ts = time.time()
                    await g.call("chat", player="boss", message=text)
                    self.orders_sent += 1
                    outcome = await self.wait_done(actor, g, n_before, ts, min(40 * 60, deadline - time.time()))
                    last = {"text": text, "outcome": outcome, "mins": (time.time() - ts) / 60}
                    jsonl(self.dir / "campaign.jsonl", {"kind": "order_done", **last})
                else:
                    mins = max(1.0, min(30.0, float(d.get("wait") or 5)))
                    say(f"{camp.name} g{self.n} waits {mins:.0f} min: {str(d.get('why'))[:120]}")
                    await asyncio.sleep(min(mins * 60, max(0, deadline - time.time())))
                    last = {"text": f"(you waited {mins:.0f} min)", "outcome": "waited", "mins": mins}
        finally:
            if actor.project and actor.project.active:
                actor.project.stop("the generation ended")
                try:
                    await asyncio.wait_for(actor.project.task, 60)
                except Exception:  # noqa: BLE001
                    pass
            stop.set()
            try:
                await asyncio.wait_for(ktask, 120)
            except Exception:  # noqa: BLE001
                pass
            p = await self.probe(pg)
            final = await self.save(pg, "final")
            summ = self.summary(actor, strat, p, time.time() - t0, final)
            (self.dir / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
            try:
                await actor.stop()
            except Exception:  # noqa: BLE001
                pass
            await jev.close()
            await asyncio.to_thread(self.inst.stop)
        return summ

    async def wait_done(self, actor, g, n_before: int, ts: float, limit: float) -> str:
        """Until the order the message made has ended (done/failed), or the limit (then the serf is told to stop)."""
        await asyncio.sleep(8)
        while time.time() - ts < limit:
            new = actor.orders[n_before:]
            busy = [o for o in actor.orders if o.status in ("new", "working", "thinking")]
            if not busy and (new or time.time() - ts > 30):
                if not new:
                    return "the serf didn't take it as an order (it may have answered instead)"
                st = [o.status for o in new]
                return ", ".join(sorted(set(st)))
            await asyncio.sleep(5)
        try:
            await g.call("chat", player="boss", message="@serf let's leave that one for now")
        except GameError:
            pass
        await asyncio.sleep(10)
        return f"not finished after {limit / 60:.0f} min (stopped)"

    def summary(self, actor, strat, p, secs: float, final: Path | None) -> dict:
        lv0 = self.probes[0]["level"] if self.probes else 0
        orders = actor.orders
        fixes = [o for o in orders if o.playbook == "fix" or o.text.startswith("(noticed)")]
        return {"gen": self.n, "stage": self.stage, "hours": round(secs / 3600, 2), "level_start": lv0,
                "level_end": p["level"] if p else None, "milestones": p["milestones"] if p else None,
                "techs": p["techs"] if p else None, "orders_sent": self.orders_sent, "orders": len(orders),
                "done": sum(o.status == "done" for o in orders), "failed": sum(o.status == "failed" for o in orders),
                "fix_share": round(len(fixes) / max(1, len(orders)), 2), "strategist_turns": strat.turns,
                "strategist_usd": round(strat.usd + sum(pr.usd for pr in actor.projects), 2),
                "projects": [{"status": pr.status, "summary": pr.summary, "turns": pr.turns, "orders": len(pr.orders)}
                             for pr in actor.projects],
                "mode": self.camp.mode, "target": self.camp.target,
                "reached_min": round(self.reached / 60, 1) if self.reached is not None else None,
                "sustained": self.sustained, "bursts": self.bursts,
                "thinker_usd": round(actor.thinker.stats.cost_usd, 2) if actor.thinker else 0,
                "final_save": str(final) if final else None}


class Campaign:
    def __init__(self, a):
        self.name, self.k, self.effort, self.strategist_effort = a.name, a.instance, a.effort, a.strategist_effort
        self.mode = a.mode
        self.target = a.target or (str(a.target_level) if a.target_level else None)
        self.order = a.order or PROJECT_ORDER
        self.goal = a.order.replace("@serf", "").replace("project:", "").strip() if a.order else GOAL
        self.dir = ROOT / "bench" / "campaigns" / a.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "campaign.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "name": a.name, "stage": a.world, "gen": 0, "gens": [], "worlds": [a.world]}

    def target_met(self, p: dict) -> bool:
        """Every milestone the target names ("5", or "7,8") is met, each on its own (not the ladder in order: an
        oil rung shouldn't wait on green science)."""
        want = {int(x) for x in str(self.target).split(",") if x.strip()}
        got = {lv for lv, name, _ in progress.MILESTONES if name in (p.get("milestones") or [])}
        return want <= got

    def target_growth(self, a: dict, b: dict) -> dict:
        """How much more of each target milestone's product was made between two probes."""
        out = {}
        for lv in (int(x) for x in str(self.target).split(",") if x.strip()):
            item = MILESTONE_ITEM.get(lv)
            if not item:
                continue
            kind = "fluids" if item == "petroleum-gas" else "items"
            out[item] = round((b.get(kind) or {}).get(item, 0) - (a.get(kind) or {}).get(item, 0))
        return out

    def save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1, default=str))

    def next_stage(self, summ: dict) -> str:
        """Carry on from the last save, unless the generation mostly fixed things and got nowhere: then a new world."""
        stuck = (summ.get("level_end") or 0) <= (summ.get("level_start") or 0) and summ.get("fix_share", 0) >= 0.5
        if stuck or not summ.get("final_save"):
            n = len(self.state["worlds"]) + 1
            name = f"campaign-{self.name}-w{n}"
            subprocess.run([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/new_world.py"), name,
                            str(1000 + 97 * n)], check=True)
            self.state["worlds"].append(name)
            say(f"{self.name}: generation {summ['gen']} stuck (fix share {summ.get('fix_share')}); new world {name}")
            return name
        stage = f"campaign-{self.name}-g{summ['gen']:02d}"
        dst = INSTALL / "saves" / f"{stage}.zip"
        if not dst.exists():
            shutil.copy2(summ["final_save"], dst)
        return stage

    async def run(self, gens: int, hours: float) -> None:
        first = self.state["gen"] + 1
        for _ in range(gens):
            self.state["gen"] += 1
            n = self.state["gen"]
            say(f"{self.name}: generation {n} from {self.state['stage']} for {hours} h")
            gen = Generation(self, n, self.state["stage"])
            try:
                summ = await gen.run(hours)
            except Exception as e:  # noqa: BLE001
                say(f"{self.name}: generation {n} crashed: {e!r}")
                summ = {"gen": n, "stage": self.state["stage"], "error": repr(e), "final_save": None,
                        "level_start": 0, "level_end": 0, "fix_share": 0}
            self.state["gens"].append(summ)
            say(f"{self.name}: generation {n} ended at milestone {summ.get('level_end')} "
                f"(from {summ.get('level_start')}), {summ.get('orders_sent')} orders, fix share {summ.get('fix_share')}")
            if summ.get("error") and self.state["gens"][-2:] and all(g.get("error") for g in self.state["gens"][-2:]):
                say(f"{self.name}: two crashed generations in a row, stopping")
                self.save_state()
                return
            if not summ.get("error"):
                self.state["stage"] = self.next_stage(summ)
            else:
                # carry on from its last half-hourly save, if it made one
                saves = sorted((self.dir / "saves").glob(f"{self.name}-g{n:02d}-*.zip"), key=lambda q: q.stat().st_mtime)
                if saves:
                    stage = f"campaign-{self.name}-g{n:02d}-recover"
                    shutil.copy2(saves[-1], INSTALL / "saves" / f"{stage}.zip")
                    self.state["stage"] = stage
                    say(f"{self.name}: carrying on from {saves[-1].name}")
            self.save_state()
            left = gens - (n - first + 1)
            if left > 0:
                # the next generation runs in a fresh process, so it gets whatever was fixed in the meantime
                argv = list(sys.argv)
                i = argv.index("--gens") if "--gens" in argv else -1
                if i >= 0:
                    argv[i + 1] = str(left)
                else:
                    argv += ["--gens", str(left)]
                say(f"{self.name}: restarting for generation {n + 1} with the current code ({left} to go)")
                sys.stdout.flush()
                os.execv(sys.executable, [sys.executable] + argv)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True)
    p.add_argument("--world", default="campaign-w1", help="the first generation's save (in server/factorio/saves)")
    p.add_argument("--gen-hours", type=float, default=3.0)
    p.add_argument("--gens", type=int, default=8)
    p.add_argument("--instance", type=int, default=75)
    p.add_argument("--reader", choices=["jev", "sonnet", "hybrid"], default="hybrid")
    p.add_argument("--effort", default=None, help="the serf's planner effort")
    p.add_argument("--strategist-effort", default=None)
    p.add_argument("--mode", choices=["strategist", "project"], default="strategist",
                   help="strategist: an outside Opus player gives every order; project: one order, the serf's own "
                        "project manager (jev/project.py) does the rest")
    p.add_argument("--target-level", type=int, default=None, help="same as --target with one milestone")
    p.add_argument("--target", default=None,
                   help="end the generation as soon as these milestones are met, e.g. 5 or 7,8 (the task ladder)")
    p.add_argument("--order", default=None, help="project mode: the order that starts it (default: beat the game)")
    a = p.parse_args()
    os.environ["JEV_READER"] = a.reader
    asyncio.run(Campaign(a).run(a.gens, a.gen_hours))


if __name__ == "__main__":
    main()
