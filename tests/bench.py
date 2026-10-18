#!/usr/bin/env python3
"""One scored benchmark run of the crew, on an isolated server instance started from a stage save.

    .venv/bin/python tests/bench.py --scenario experiments/scenarios/s4-ghost-build.json --variant baseline \
        [--minutes N] [--instance K] [--agents N] [--model M] [--dry [--selftest]] [--run-id ID]

Flow: copy the stage into instance K and start it -> cancel leftover agent jobs, drain stale chat -> run the
scenario's setup_lua -> measure the checks (baseline) -> start the Orchestrator in-process with a generated
crew.toml (state in experiments/runs/<run_id>/state) -> say the goal in chat as player "ops" -> sample the checks
every minute (timeline.jsonl) -> final score, behaviour metrics -> result.json. The instance is always stopped.

--dry skips the agents: setup + scoring only (with --selftest, the scenario's selftest_lua runs first, which should
fake success, e.g. revive the ghosts, so the scorer can be checked end to end). No LLM usage in dry mode.

Scenario JSON: name, stage, goal, minutes, agents ([{name, role, focus, model}] or count), setup_lua, selftest_lua,
stop_on_success (default true), score: [{name, lua, target?, target_mult_baseline?, rate?, weight?}].
`lua` is an expression (or a chunk with `return`) evaluated by the mod's eval op with helpers in scope:
s (nauvis), f (player force), st (item production stats), pm(item[, 'input'|'output']) (per minute, last minute),
count(entity), making(recipe) (assemblers set to it), finished(recipe) (sum of products_finished on them).
rate=true: the value is cumulative and is scored as its increase per game minute over the last sample interval.
target_mult_baseline=X: target = X * the value measured just after setup.
Variants come from experiments/variants.json (or a path); see that file. A variant's "experiment" dict becomes the
crew.toml [experiment] table (crew flags such as idle_sweep, pipeline_prompt, work_tool; all default true).
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import logging
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from crew import progress  # noqa: E402
from crew.rcon import Crew, GameError, Rcon, RconError  # noqa: E402
from instance import Instance  # noqa: E402

EXP = ROOT / "experiments"
RUNS = EXP / "runs"
RESULTS = EXP / "results.jsonl"
LOG = EXP / "log.jsonl"
DEFAULT_MODEL = "claude-opus-5-5"

PRELUDE = """local s=game.surfaces.nauvis local f=game.forces.player
local st=f.get_item_production_statistics(s)
local function pm(n,cat) return st.get_flow_count{name=n,category=cat or 'input',
  precision_index=defines.flow_precision_index.one_minute,count=true} end
local function count(n) return s.count_entities_filtered{name=n,force='player'} end
local function machines(r) local out={} for _,e in pairs(s.find_entities_filtered{type={'assembling-machine','furnace'},force='player'}) do
  local ok,rr=pcall(e.get_recipe)
  local name=ok and rr and rr.name
  if not name and e.type=='furnace' then  -- idle furnaces only remember their last recipe
    local okp,pr=pcall(function() return e.previous_recipe end)
    name=okp and pr and (pr.name or (pr.name==nil and type(pr)=='table' and pr[1])) or nil
    if type(name)=='table' then name=name.name end
  end
  if name==r then out[#out+1]=e end end return out end
local function making(r) return #machines(r) end
local function finished(r) local k=0 for _,e in pairs(machines(r)) do k=k+e.products_finished end return k end
"""


# ---------------------------------------------------------------------- small helpers
def now_s() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def log_event(kind: str, **kw) -> None:
    append_jsonl(LOG, {"t": time.time(), "time": now_s(), "kind": kind, **kw})


def chunk(lua: str) -> str:
    body = lua if re.search(r"\breturn\b", lua) else f"return ({lua})"
    return PRELUDE + body


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {toml_value(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"can't write {v!r} to TOML")


def to_toml(d: dict) -> str:
    """Enough TOML for crew.toml: scalars, [tables], [[arrays of tables]]."""
    lines = [f"{k} = {toml_value(v)}" for k, v in d.items() if not isinstance(v, dict) and not
             (isinstance(v, list) and v and all(isinstance(x, dict) for x in v))]
    for k, v in d.items():
        if isinstance(v, dict):
            lines += ["", f"[{k}]"] + [f"{kk} = {toml_value(vv)}" for kk, vv in v.items() if vv is not None]
    for k, v in d.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for item in v:
                lines += ["", f"[[{k}]]"] + [f"{kk} = {toml_value(vv)}" for kk, vv in item.items() if vv is not None]
    return "\n".join(lines) + "\n"


def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def git_info() -> dict:
    try:
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "crew", "mod"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return {"commit": head, "dirty_files": dirty.splitlines()[:30]}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def load_variant(name: str, path: Path | None) -> dict:
    p = path or EXP / "variants.json"
    variants = json.loads(p.read_text()) if p.exists() else {}
    if name not in variants:
        if name == "baseline":
            return {}
        raise SystemExit(f"unknown variant {name!r}; known: {', '.join(variants)} (edit {p})")
    return variants[name]


def build_agents(scn: dict, var: dict, n: int | None, model: str | None) -> list[dict]:
    spec = scn.get("agents", var.get("agents", 1))
    if isinstance(var.get("agents"), (int, list)):
        spec = var["agents"]
    agents = [dict(a) for a in spec] if isinstance(spec, list) else []
    count = n or (len(agents) if agents else int(spec))
    for i in range(len(agents), count):
        agents.append({"name": f"claude-{i + 1}"})
    agents = agents[:count]
    for i, a in enumerate(agents):
        a.setdefault("role", "foreman" if i == 0 else "worker")
        for key in (str(i), a["name"]):
            a.update((var.get("agent_overrides") or {}).get(key, {}))
        if var.get("model"):
            a["model"] = var["model"]
        if model:
            a["model"] = model
    return agents


def crew_toml(inst: Instance, state_dir: Path, agents: list[dict], var: dict, model: str | None) -> dict:
    defaults = {"backend": var.get("backend", "claude-code"), "model": model or var.get("model") or DEFAULT_MODEL,
                "max_turns_per_hour": 120, **(var.get("defaults") or {})}
    d: dict = {"state_dir": str(state_dir), "starter_kit": True,
               "server": {"host": inst.host, "rcon_port": inst.rcon_port, "rcon_password_file": str(inst.pwfile)},
               "defaults": defaults, "agent": agents}
    adv = var.get("advisor", False)
    if adv:
        d["advisor"] = adv if isinstance(adv, dict) else {"name": "architect", "model": "claude-opus-5-5",
                                                          "effort": "high"}
    if var.get("experiment"):  # crew flags: [experiment] idle_sweep / pipeline_prompt / work_tool ...
        d["experiment"] = dict(var["experiment"])
    return deep_merge(d, var.get("toml") or {})


# ---------------------------------------------------------------------- scoring
class Scorer:
    def __init__(self, crew: Crew, checks: list[dict]):
        self.crew, self.checks = crew, checks
        self.prev: dict[str, tuple[float, int]] = {}  # rate checks: name -> (raw value, tick)
        self.baseline: dict[str, float | None] = {}
        self.targets: dict[str, float | None] = {c["name"]: c.get("target") for c in checks}
        self.reached: dict[str, float] = {}  # name -> seconds since run start when the target was first met

    async def eval(self, lua: str, timeout: float = 30):
        return (await asyncio.wait_for(self.crew.call("eval", code=chunk(lua)), timeout)).get("result")

    async def sample(self) -> dict:
        tick = await self.eval("game.tick")
        out: dict = {"tick": tick, "values": {}, "errors": {}}
        for c in self.checks:
            try:
                v = await self.eval(c["lua"])
                v = float(v) if isinstance(v, (int, float)) else (float(bool(v)) if isinstance(v, bool) else v)
            except (GameError, RconError, asyncio.TimeoutError) as e:
                out["errors"][c["name"]] = str(e)[:300]
                v = None
            if c.get("rate") and isinstance(v, float):
                raw = v
                p = self.prev.get(c["name"])
                v = None if not p or tick <= p[1] else max(0.0, raw - p[0]) / ((tick - p[1]) / 3600)
                self.prev[c["name"]] = (raw, tick)
                out.setdefault("raw", {})[c["name"]] = raw
            out["values"][c["name"]] = v
        return out

    def set_baseline(self, sample: dict) -> None:
        self.baseline = dict(sample["values"])
        for c in self.checks:
            m = c.get("target_mult_baseline")
            if m is not None:
                b = self.baseline.get(c["name"]) or 0.0
                self.targets[c["name"]] = round(m * b, 3) if b > 0 else c.get("target")
            dlt = c.get("target_delta")
            if dlt is not None:  # e.g. "6 more techs than at the start"
                self.targets[c["name"]] = float((self.baseline.get(c["name"]) or 0.0) + dlt)

    def note(self, sample: dict, elapsed: float) -> bool:
        """Record time-to-target; True when every check with a target is met."""
        met_all, any_target = True, False
        for name, v in sample["values"].items():
            t = self.targets.get(name)
            if t is None:
                continue
            any_target = True
            if isinstance(v, float) and v >= t:
                self.reached.setdefault(name, round(elapsed, 1))
            else:
                met_all = False
        return any_target and met_all

    def report(self, final: dict) -> dict:
        scores, fracs, weights = {}, [], []
        for c in self.checks:
            n = c["name"]
            v, t = final["values"].get(n), self.targets.get(n)
            frac = None
            if t is not None and isinstance(v, float):
                if c.get("target_delta"):  # progress from the starting value, not from zero
                    b = self.baseline.get(n) or 0.0
                    frac = round(max(0.0, min((v - b) / c["target_delta"], 1.0)), 4)
                else:
                    frac = 1.0 if t <= 0 else round(min(v / t, 1.0), 4)
            scores[n] = {"value": v, "baseline": self.baseline.get(n), "target": t, "frac": frac,
                         "time_to_target_s": self.reached.get(n), "error": final["errors"].get(n)}
            if t is not None:
                fracs.append(frac or 0.0)
                weights.append(float(c.get("weight", 1)))
        total = round(sum(f * w for f, w in zip(fracs, weights)) / sum(weights), 4) if weights else None
        return {"checks": scores, "score": total,
                "success": bool(weights) and all(scores[c["name"]]["frac"] == 1.0
                                                 for c in self.checks if self.targets.get(c["name"]) is not None)}


# ---------------------------------------------------------------------- behaviour metrics
FAIL_RE = re.compile(r"#\d+ \w+: FAILED")


def _actions(args) -> list[dict]:
    acts = (args or {}).get("actions")
    if isinstance(acts, str):
        try:
            acts = json.loads(acts)
        except json.JSONDecodeError:
            return []
    return [a for a in acts or [] if isinstance(a, dict)]


def transcript_metrics(path: Path, t_start: float, t_end: float) -> dict:
    m = {"turns": 0, "tool_calls": 0, "tools": Counter(), "act_ops": Counter(), "hand_logistics": 0,
         "failures": 0, "tool_secs": 0.0, "turn_secs": 0.0, "turns_ended_idle": 0, "cost_usd": 0.0,
         "input_tokens": 0, "output_tokens": 0, "turn_errors": 0, "thoughts": 0, "turns_incomplete": 0,
         "incomplete_secs": 0.0}
    open_tools: dict[str, list[float]] = defaultdict(list)
    turn_mode, open_prompt = None, None
    if not path.exists():
        return {**m, "missing": True}
    for line in path.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not t_start - 5 <= r.get("t", 0) <= t_end + 120:
            continue  # transcripts append; only count this run's window
        k = r.get("kind")
        if k == "prompt":
            turn_mode, open_prompt = None, r["t"]
        elif k == "tool":
            m["tool_calls"] += 1
            m["tools"][r.get("name")] += 1
            open_tools[r.get("name")].append(r["t"])
            if r.get("name") == "status":
                turn_mode = (r.get("args") or {}).get("mode", "working")
            if r.get("name") == "act":
                for a in _actions(r.get("args")):
                    op = a.get("op", "?")
                    m["act_ops"][op] += 1
                    if op in ("insert", "take"):
                        m["hand_logistics"] += 1
        elif k == "result":
            q = open_tools.get(r.get("name"))
            if q:
                m["tool_secs"] += max(0.0, r["t"] - q.pop(0))
            for ln in str(r.get("out", "")).splitlines():
                if FAIL_RE.search(ln) and "skipped" not in ln:
                    m["failures"] += 1
        elif k == "thought":
            m["thoughts"] += 1
        elif k == "turn":
            m["turns"] += 1
            open_prompt = None
            m["turn_secs"] += float(r.get("secs") or 0)
            m["cost_usd"] += float(r.get("cost") or 0)
            m["input_tokens"] += int(r.get("input_tokens") or 0)
            m["output_tokens"] += int(r.get("output_tokens") or 0)
            m["turn_errors"] += 1 if r.get("error") else 0
            if (turn_mode or "idle") == "idle":
                m["turns_ended_idle"] += 1
    if open_prompt is not None:  # a turn cut off when the run stopped: its cost is unknown (not in cost_usd)
        m["turns_incomplete"], m["incomplete_secs"] = 1, round(max(0.0, t_end - open_prompt), 1)
    run_secs = max(1.0, t_end - t_start)
    m["tools"], m["act_ops"] = dict(m["tools"].most_common()), dict(m["act_ops"].most_common())
    m.update(tool_secs=round(m["tool_secs"], 1), turn_secs=round(m["turn_secs"], 1),
             cost_usd=round(m["cost_usd"], 4), run_secs=round(run_secs, 1),
             tool_frac_of_run=round(m["tool_secs"] / run_secs, 3),
             turn_frac_of_run=round(m["turn_secs"] / run_secs, 3),
             model_secs=round(max(0.0, m["turn_secs"] - m["tool_secs"]), 1))
    return m


def behavior(state_dir: Path, names: list[str], t_start: float, t_end: float,
             list_start: dict, list_end: dict, busy_samples: dict) -> dict:
    per: dict = {}
    for n in names:
        m = transcript_metrics(state_dir / "agents" / n / "transcript.jsonl", t_start, t_end)
        s0 = (list_start.get(n) or {}).get("stats")
        s1 = (list_end.get(n) or {}).get("stats")
        if isinstance(s1, dict):
            d = {k: s1.get(k, 0) - ((s0 or {}).get(k, 0) if isinstance(s0, dict) else 0)
                 for k in ("busy_ticks", "idle_ticks", "crafting_ticks")}
            tot = d["busy_ticks"] + d["idle_ticks"]
            m["mod_stats"] = {**d, "idle_pct": round(100 * d["idle_ticks"] / tot, 1) if tot else None,
                              "crafting_pct": round(100 * d["crafting_ticks"] / tot, 1) if tot else None}
        else:
            m["mod_stats"] = None
        b = busy_samples.get(n) or [0, 0]
        m["sampled_busy_pct"] = round(100 * b[0] / b[1], 1) if b[1] else None
        m["alive_at_end"] = (list_end.get(n) or {}).get("alive")
        per[n] = m
    keys = ("turns", "turns_incomplete", "tool_calls", "hand_logistics", "failures", "turns_ended_idle", "cost_usd", "tool_secs",
            "turn_secs", "input_tokens", "output_tokens")
    total = {k: round(sum(p[k] for p in per.values()), 4) for k in keys}
    idle = [p["mod_stats"]["idle_pct"] for p in per.values() if p.get("mod_stats") and p["mod_stats"]["idle_pct"] is not None]
    total["char_idle_pct_mean"] = round(sum(idle) / len(idle), 1) if idle else None
    busy = [p["sampled_busy_pct"] for p in per.values() if p["sampled_busy_pct"] is not None]
    total["sampled_busy_pct_mean"] = round(sum(busy) / len(busy), 1) if busy else None
    acts = Counter()
    for p in per.values():
        acts.update(p["act_ops"])
    total["act_ops"] = dict(acts.most_common())
    return {"agents": per, "total": total}


# ---------------------------------------------------------------------- the run
class Bench:
    def __init__(self, args):
        self.args = args
        self.scn = json.loads(Path(args.scenario).read_text())
        self.var = load_variant(args.variant, Path(args.variants) if args.variants else None)
        self.minutes = float(args.minutes if args.minutes is not None else self.scn.get("minutes", 10))
        self.run_id = args.run_id or (time.strftime("%Y%m%d-%H%M%S") +
                                      f"-{self.scn['name']}-{args.variant}" + ("-dry" if args.dry else ""))
        self.dir = RUNS / self.run_id
        self.state = self.dir / "state"
        self.inst = Instance(args.instance, self.scn["stage"])
        self.stop_evt = asyncio.Event()
        self.result: dict = {"run_id": self.run_id, "scenario": self.scn["name"], "variant": args.variant,
                             "instance": args.instance, "stage": self.scn["stage"], "dry": args.dry,
                             "minutes_planned": self.minutes, "errors": []}

    def _err(self, what: str, e: BaseException) -> None:
        self.result["errors"].append(f"{what}: {e!r}"[:500])
        print(f"bench: {what} failed: {e!r}", flush=True)

    async def run(self) -> dict:
        a = self.args
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a.scenario, self.dir / "scenario.json")
        (self.dir / "variant.json").write_text(json.dumps({"name": a.variant, **self.var}, indent=1))
        self.result.update(start=now_s(), t_start=time.time(), git=git_info())
        print(f"bench: run {self.run_id} on instance {a.instance} (stage {self.scn['stage']})", flush=True)
        await asyncio.to_thread(self.inst.start, 240)
        orch = None
        rcon = Rcon(self.inst.host, self.inst.rcon_port, self.inst.password)
        try:
            await rcon.connect()
            crew = self.crew = Crew(rcon)
            self.result["mod_version"] = (await crew.call("ping")).get("version")
            await self._reset_agents(crew)
            setup = {}
            if self.scn.get("setup_lua"):
                setup = await asyncio.wait_for(crew.call("eval", code=chunk(self.scn["setup_lua"])), 60)
                setup = setup.get("result") if isinstance(setup, dict) else setup
            self.result["setup"] = setup
            scorer = Scorer(crew, self.scn.get("score", []))
            base = await scorer.sample()  # rate checks have no baseline value; this sample is their start point
            scorer.set_baseline(base)
            self.result["baseline"] = base
            self.result["targets"] = scorer.targets
            self.result["summary_start"] = await progress.summary(crew.call)
            list_start = {x["name"]: x for x in (await crew.call("list"))["agents"]}
            goal = self._goal(setup)
            self.result["goal"] = goal
            agents = build_agents(self.scn, self.var, a.agents, a.model)
            names = [x["name"] for x in agents]
            busy: dict[str, list[int]] = {n: [0, 0] for n in names}
            timeline = self.dir / "timeline.jsonl"
            t0 = time.time()

            if a.dry:
                if a.selftest and self.scn.get("selftest_lua"):
                    self.result["selftest"] = (await crew.call("eval", code=chunk(self.scn["selftest_lua"]))).get("result")
                if a.minutes:
                    await self._sample_loop(scorer, crew, busy, timeline, t0, self.minutes * 60)
            else:
                cfg_d = crew_toml(self.inst, self.state, agents, self.var, a.model)
                (self.dir / "crew.toml").write_text(to_toml(cfg_d))
                from crew import config as config_mod
                from crew.orchestrator import Orchestrator
                cfg = config_mod.load(self.dir / "crew.toml")
                self.result["config"] = {"agents": agents, "advisor": cfg_d.get("advisor"),
                                         "defaults": cfg_d["defaults"], "experiment": cfg_d.get("experiment")}
                orch = Orchestrator(cfg)

                async def no_snapshot(label: str) -> None:  # don't write the shared manifest or saves dir
                    append_jsonl(self.dir / "events.jsonl", {"t": time.time(), "kind": "milestone", "label": label})
                orch._snapshot = no_snapshot
                await asyncio.wait_for(orch.start(), 180)
                t0 = time.time()
                self.result["t_agents_start"] = t0
                await asyncio.sleep(1)
                await crew.call("chat", player="ops", message=goal)
                append_jsonl(timeline, {"t": t0, "event": "goal", "text": goal})
                await self._sample_loop(scorer, crew, busy, timeline, t0, self.minutes * 60)
            t_end = time.time()
            self.result["elapsed_s"] = round(t_end - t0, 1)

            final = await scorer.sample()
            append_jsonl(timeline, {"t": t_end, "elapsed": round(t_end - t0, 1), "final": True, **final})
            self.result["final"] = final
            self.result.update(scorer.report(final))
            self.result["summary_end"] = await progress.summary(crew.call)
            list_end = {x["name"]: x for x in (await crew.call("list"))["agents"]}
            self.result["agents_end"] = list_end
            if orch:
                self.result["drain_s"] = await self._drain(orch)
                await self._stop_orch(orch)
                orch = None
            self.result["behavior"] = behavior(self.state, names, t0, time.time(), list_start, list_end, busy)
            self.result["cost_usd"] = self.result["behavior"]["total"]["cost_usd"]
            if not a.no_final_save:
                await self._final_save(rcon)
        except Exception as e:  # noqa: BLE001
            self._err("run", e)
        finally:
            if orch:
                await self._stop_orch(orch)
            await rcon.close()
            await asyncio.to_thread(self.inst.stop)
            self.result.update(end=now_s(), t_end=time.time())
            (self.dir / "result.json").write_text(json.dumps(self.result, indent=1, default=str))
        return self.result

    def _goal(self, setup) -> str:
        goal = self.scn["goal"]
        if isinstance(setup, dict):
            goal = re.sub(r"\{(\w+)\}", lambda m: str(setup.get(m.group(1), m.group(0))), goal)
        if "@" not in goal:
            goal = "@all " + goal
        return goal

    async def _reset_agents(self, crew: Crew) -> None:
        """Deterministic start: no leftover jobs from the session the stage was saved in, no stale chat."""
        for x in (await crew.call("list"))["agents"]:
            try:
                await crew.call("cancel", agent=x["name"], reason="bench reset")
                await crew.call("status", agent=x["name"], text="")
            except GameError:
                pass
        await crew.call("poll")

    async def _sample_loop(self, scorer: Scorer, crew: Crew, busy, timeline: Path, t0: float, secs: float) -> None:
        next_sample = t0 + 60
        stop_ok = self.scn.get("stop_on_success", True) and not self.args.no_early_stop
        while not self.stop_evt.is_set():
            now = time.time()
            if now - t0 >= secs:
                break
            try:
                ls = (await asyncio.wait_for(crew.call("list"), 15))["agents"]
                for x in ls:
                    if x["name"] in busy:
                        busy[x["name"]][1] += 1
                        busy[x["name"]][0] += 1 if (x.get("job") or x.get("queued")) else 0
                if now >= next_sample:
                    next_sample += 60
                    smp = await scorer.sample()
                    smp["agents"] = {x["name"]: {"job": x.get("job"), "queued": x.get("queued"), "stats": x.get("stats"),
                                                 "position": x.get("position")} for x in ls if x["name"] in busy}
                    append_jsonl(timeline, {"t": now, "elapsed": round(now - t0, 1), **smp})
                    print(f"bench: {round((now - t0) / 60, 1)} min: {smp['values']}", flush=True)
                    if scorer.note(smp, now - t0) and stop_ok:
                        print("bench: all targets met; stopping early", flush=True)
                        self.result["stopped_early"] = True
                        break
            except (GameError, RconError, asyncio.TimeoutError) as e:
                self._err("sample", e)
                if not self.inst.running():
                    raise RuntimeError("server died during the run") from e
            try:
                await asyncio.wait_for(self.stop_evt.wait(), 5)
            except asyncio.TimeoutError:
                pass
        if self.stop_evt.is_set():
            self.result["interrupted"] = True

    async def _drain(self, orch) -> float:
        """After scoring, let in-flight turns finish (up to --drain seconds) so their cost gets recorded.
        Stops at the first moment no agent is mid-turn. The score is already taken, so this doesn't change it."""
        t0 = time.time()
        while time.time() - t0 < self.args.drain and not self.stop_evt.is_set():
            if not any(getattr(x, "in_turn", False) for x in orch.agents.values()):
                break
            await asyncio.sleep(1)
        return round(time.time() - t0, 1)

    async def _stop_orch(self, orch) -> None:
        try:
            await asyncio.wait_for(orch.stop(), 60)
        except BaseException as e:  # noqa: BLE001
            self._err("orchestrator stop", e)
        me = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=15)
        try:
            await orch.link.rcon.close()
        except Exception:  # noqa: BLE001
            pass
        for n in orch.agents:  # characters stay; make sure they stop moving
            try:
                await asyncio.wait_for(self.crew.call("cancel", agent=n, reason="bench over"), 10)
            except Exception:  # noqa: BLE001
                pass

    async def _final_save(self, rcon: Rcon) -> None:
        try:
            await rcon.command("/server-save bench-final", timeout=60)
            p = self.inst.dir / "saves" / "bench-final.zip"
            for _ in range(60):
                if p.exists() and p.stat().st_size > 0:
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(1)
            shutil.copy2(p, self.dir / "final.zip")
            self.result["final_save"] = str(self.dir / "final.zip")
        except Exception as e:  # noqa: BLE001
            self._err("final save", e)


def record(result: dict, append: bool = True) -> dict:
    """One line for experiments/results.jsonl (appended unless append=False)."""
    beh = (result.get("behavior") or {}).get("total") or {}
    line = {k: result.get(k) for k in ("run_id", "scenario", "variant", "instance", "stage", "dry", "start", "end",
                                       "elapsed_s", "score", "success", "stopped_early", "interrupted", "cost_usd")}
    line["scores"] = {n: {k: c.get(k) for k in ("value", "target", "frac", "time_to_target_s")}
                      for n, c in ((result.get("checks") or {}).items())}
    line["behavior"] = {k: beh.get(k) for k in ("turns", "turns_incomplete", "tool_calls", "hand_logistics", "failures", "turns_ended_idle",
                                                "char_idle_pct_mean", "sampled_busy_pct_mean", "tool_secs", "turn_secs")}
    line["advisor"] = bool((result.get("config") or {}).get("advisor"))
    line["experiment"] = (result.get("config") or {}).get("experiment")
    line["models"] = sorted({a.get("model") for a in ((result.get("config") or {}).get("agents") or []) if a.get("model")})
    line["errors"] = result.get("errors")
    if append:
        append_jsonl(RESULTS, line)
    return line


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", required=True)
    p.add_argument("--variant", default="baseline")
    p.add_argument("--variants", help="variants JSON (default experiments/variants.json)")
    p.add_argument("--minutes", type=float)
    p.add_argument("--instance", type=int, default=1)
    p.add_argument("--agents", type=int, help="number of agents (overrides scenario)")
    p.add_argument("--model", help="model for every agent (overrides scenario and variant)")
    p.add_argument("--run-id")
    p.add_argument("--dry", action="store_true", help="no agents: setup + scoring only (no LLM usage)")
    p.add_argument("--selftest", action="store_true", help="with --dry: run the scenario's selftest_lua first")
    p.add_argument("--no-early-stop", action="store_true", help="keep going after all targets are met")
    p.add_argument("--no-final-save", action="store_true")
    p.add_argument("--drain", type=float, default=90,
                   help="after scoring, wait up to this many seconds for in-flight turns to finish (cost accounting)")
    p.add_argument("--no-record", action="store_true", help="don't append to experiments/results.jsonl / log.jsonl")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    if a.dry and a.minutes is None:
        a.minutes = 0
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    bench = Bench(a)
    atexit.register(bench.inst.stop)  # belt and braces: never leave a server behind
    record_it = not a.no_record and not a.dry

    async def go():
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(sig, bench.stop_evt.set)
        if record_it:
            log_event("run_start", run_id=bench.run_id, scenario=bench.scn["name"], variant=a.variant, instance=a.instance)
        hard = bench.minutes * 60 + 900
        try:
            return await asyncio.wait_for(bench.run(), hard)
        except asyncio.TimeoutError:
            bench._err("hard timeout", TimeoutError(hard))
            return bench.result

    res = asyncio.run(go())
    if record_it:
        line = record(res)
        log_event("run_end", run_id=bench.run_id, score=line["score"], cost_usd=line["cost_usd"], errors=line["errors"])
    print(json.dumps({k: res.get(k) for k in ("run_id", "score", "success", "elapsed_s", "cost_usd", "errors")}
                     | {"checks": {n: (c["value"], c["target"]) for n, c in (res.get("checks") or {}).items()}},
                     default=str))
    sys.exit(0 if not res.get("errors") else 1)


if __name__ == "__main__":
    main()
