"""The serf's own layer: scripts and playbooks it writes for itself on top of the core tools.

The core (mod, tools, prompt) is maintained by people; this layer is the agent's. It grows while the serf works:
- playbook: a short how-to in words ("how I hook a smelter column to an ore patch"), read back with skill_read.
- script: a small program in a safe subset of Python that calls core tools (act, build, find, inspect, ...),
  run with skill_run. Scripts can only do what the serf's own tools do, so the game's rules still hold.

Library: one <name>.json per skill in SERF_SKILLS_DIR (default ~/.local/state/factorio-serf/skills), plus
usage.jsonl (every run: ok or not, how long, the error). SERF_LIBRARY_FROZEN=1 makes it read-only (held-out tests).
Scripts never get imports, files, the network, dunder attributes or str.format: in multiplayer, other players'
chat reaches the serf, so whatever it writes must be harmless.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import _home

if TYPE_CHECKING:
    from .agent import Agent

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_CODE = 6000
MAX_TEXT = 3000
SCRIPT_SECS = 240  # wall time per script run
MAX_TOOL_CALLS = 60
MAX_LOOP_STEPS = 20000
MAX_DEPTH = 3  # scripts calling scripts


def skills_dir() -> Path:
    if os.environ.get("SERF_SKILLS_DIR"):
        return Path(os.environ["SERF_SKILLS_DIR"])
    return _home("~/.local/state", "factorio-serf") / "skills"


def frozen() -> bool:
    return os.environ.get("SERF_LIBRARY_FROZEN") == "1"


def load_all() -> dict[str, dict]:
    d = skills_dir()
    out = {}
    if d.exists():
        for p in sorted(d.glob("*.json")):
            try:
                s = json.loads(p.read_text())
                out[s["name"]] = s
            except (ValueError, KeyError):
                continue
    return out


def stats() -> dict[str, dict]:
    """uses / ok / last error per skill, from usage.jsonl."""
    out: dict[str, dict] = {}
    p = skills_dir() / "usage.jsonl"
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        try:
            u = json.loads(line)
        except ValueError:
            continue
        s = out.setdefault(u["name"], {"uses": 0, "ok": 0, "err": ""})
        s["uses"] += 1
        s["ok"] += bool(u.get("ok"))
        if not u.get("ok"):
            s["err"] = u.get("err", "")[:120]
    return out


def render_index(limit: int = 30) -> str:
    """The library as shown to the serf every turn: one line per skill, most used first."""
    sk, st = load_all(), stats()
    if not sk:
        return ""
    rows = sorted(sk.values(), key=lambda s: -st.get(s["name"], {}).get("uses", 0))[:limit]
    lines = []
    for s in rows:
        u = st.get(s["name"])
        use = f" [{u['ok']}/{u['uses']} ok]" if u else ""
        if s["kind"] == "script":
            lines.append(f"- {s['name']}({', '.join(s.get('params') or [])}) script: {s['doc']}{use}")
        else:
            lines.append(f"- {s['name']} playbook: {s['doc']}")
    more = len(sk) - len(rows)
    return "\n".join(lines) + (f"\n(+{more} more: skill_read name=list)" if more > 0 else "")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def save(name: str, kind: str, doc: str, *, code: str = "", text: str = "", params: list[str] | None = None,
         author: str = "", run: str = "") -> str:
    if frozen():
        return "error: the library is read-only in this run"
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        return "error: name must be lowercase letters, digits and _, 2-40 chars, starting with a letter"
    doc = re.sub(r"\s+", " ", doc or "").strip()
    if not doc:
        return "error: give a one-line doc: what it does and when to use it"
    entry: dict[str, Any] = {"name": name, "kind": kind, "doc": doc[:200], "author": author, "run": run}
    if kind == "script":
        if len(code) > MAX_CODE:
            return f"error: script is {len(code)} chars; keep it under {MAX_CODE}"
        params = [p for p in (params or []) if isinstance(p, str)]
        try:
            check(code, params)
        except ScriptError as e:
            return f"error: {e}"
        entry.update(code=code, params=params)
    elif kind == "playbook":
        if not text.strip():
            return "error: a playbook needs text"
        entry["text"] = text.strip()[:MAX_TEXT]
    else:
        return "error: kind is script or playbook"
    d = skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.json"
    old = json.loads(path.read_text()) if path.exists() else None
    entry["version"] = (old or {}).get("version", 0) + 1
    entry["created"] = (old or {}).get("created") or time.strftime("%Y-%m-%d %H:%M:%S")
    entry["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_atomic(path, json.dumps(entry, indent=1))
    with open(d / "history.jsonl", "a") as f:  # every version, for the morning review
        f.write(json.dumps(entry) + "\n")
    return f"{kind} {name} {'updated (v' + str(entry['version']) + ')' if old else 'saved'}"


def friction(note: str, agent: str = "", run: str = "") -> str:
    """Something slowed the serf down or confused it, logged the moment it happens (read in the morning review)."""
    note = re.sub(r"\s+", " ", note or "").strip()
    if not note:
        return "error: say what got in your way"
    d = skills_dir().parent
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "friction.jsonl", "a") as f:
        f.write(json.dumps({"t": time.time(), "agent": agent, "run": run, "note": note[:500]}) + "\n")
    return "noted for the people who maintain your tools; carry on"


def record_use(name: str, ok: bool, secs: float, err: str = "", run: str = "") -> None:
    d = skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "usage.jsonl", "a") as f:
        f.write(json.dumps({"t": time.time(), "name": name, "ok": ok, "secs": round(secs, 1), "err": err[:300],
                            "run": run}) + "\n")


# ------------------------------------------------------------------ the safe subset
class ScriptError(Exception):
    pass


ALLOWED = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Load, ast.Store, ast.Constant, ast.JoinedStr,
    ast.FormattedValue, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp,
    ast.GeneratorExp, ast.comprehension, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.If,
    ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.Return, ast.Call, ast.keyword, ast.Attribute,
    ast.Subscript, ast.Slice, ast.Starred, ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)
BAD_ATTRS = {"format", "format_map", "mro", "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await",
             "cr_origin", "ag_frame", "f_globals", "f_locals", "f_back", "f_builtins", "tb_frame"}


def _range(*a):
    r = range(*a)
    if len(r) > 100000:
        raise ScriptError("range over 100000 steps")
    return r
SAFE_BUILTINS = {
    "len": len, "range": _range, "min": min, "max": max, "abs": abs, "round": round, "int": int, "float": float,
    "str": str, "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple, "sorted": sorted,
    "enumerate": enumerate, "zip": zip, "sum": sum, "any": any, "all": all, "reversed": reversed,
    "True": True, "False": False, "None": None,
}
TOOL_NAMES = ["act", "wait", "look", "map", "find", "inspect", "trace", "production", "diagnose", "recipes",
              "techs", "build", "stamp", "designs", "say", "find_space", "skill"]
HELPERS = ["parse", "failed", "log", "args"]


def check(code: str, params: list[str] | None = None) -> ast.Module:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ScriptError(f"syntax error line {e.lineno}: {e.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ScriptError(f"line {getattr(node, 'lineno', '?')}: {type(node).__name__} is not allowed in scripts "
                              "(no def, lambda, import, class, try, with, global)")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ScriptError(f"line {node.lineno}: names can't start with _")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BAD_ATTRS):
            raise ScriptError(f"line {node.lineno}: .{node.attr} is not allowed (use f-strings, not .format)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and not (
                isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) and 0 <= node.right.value <= 8):
            raise ScriptError(f"line {node.lineno}: ** only with a small constant exponent")
    return tree


class _Rewrite(ast.NodeTransformer):
    """Tool calls become awaits; every loop body starts with a step counter (so a runaway loop stops)."""

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in TOOL_NAMES:
            return ast.copy_location(ast.Await(node), node)
        return node

    def _loop(self, node):
        self.generic_visit(node)
        tick = ast.Expr(ast.Await(ast.Call(ast.Name("_tick", ast.Load()), [], [])))
        node.body.insert(0, tick)
        return node

    visit_For = _loop
    visit_While = _loop


def _compile(code: str):
    tree = check(code)
    tree = _Rewrite().visit(tree)
    fn = ast.AsyncFunctionDef(name="_main", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[],
                                                                 defaults=[]),
                              body=tree.body or [ast.Pass()], decorator_list=[], returns=None, type_params=[])
    mod = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(mod)
    return compile(mod, "<skill>", "exec")


def parse(text: Any) -> Any:
    """The first JSON object/array in a tool's text, or None."""
    if not isinstance(text, str):
        return text
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return json.JSONDecoder().raw_decode(text[i:])[0]
            except ValueError:
                continue
    return None


def failed(text: Any) -> bool:
    t = str(text)
    return any(k in t for k in ("FAILED", "exception:", "game error", "bad arguments", "error:"))


async def run(agent: "Agent", name: str, args: dict, depth: int = 0) -> tuple[bool, str]:
    """Run a script. Returns (ok, transcript of what it did)."""
    from . import tools as T

    sk = load_all().get(name)
    if not sk:
        return False, f"no skill called {name}"
    if sk["kind"] != "script":
        return True, f"{name} is a playbook:\n{sk['text']}"
    if depth >= MAX_DEPTH:
        return False, "scripts may call scripts only 3 deep"
    trace: list[str] = []
    state = {"calls": 0, "steps": 0}

    async def _tick():
        state["steps"] += 1
        if state["steps"] > MAX_LOOP_STEPS:
            raise ScriptError(f"loop ran over {MAX_LOOP_STEPS} steps")
        if state["steps"] % 200 == 0:
            await asyncio.sleep(0)

    def tool(tname: str):
        async def call(*pos, **kw):
            if agent.interrupted.is_set():
                raise ScriptError("stopped: a human said something")
            state["calls"] += 1
            if state["calls"] > MAX_TOOL_CALLS:
                raise ScriptError(f"over {MAX_TOOL_CALLS} tool calls")
            if tname == "skill":
                sub = kw.pop("name", pos[0] if pos else "")
                ok, out = await run(agent, sub, kw, depth + 1)
                trace.append(f"skill {sub}: {'ok' if ok else 'FAILED'}")
                return out
            if tname == "act" and pos:
                kw["actions"] = list(pos[0]) if len(pos) == 1 and isinstance(pos[0], list) else list(pos)
            h = T.BY_NAME[tname].handler
            out = await h(agent, kw)
            if tname == "act":  # scripts wait for the whole batch
                for _ in range(12):
                    if not agent.pending_jobs:
                        break
                    out += "\n" + await T.BY_NAME["wait"].handler(agent, {"seconds": 60})
            elif tname == "build":
                for _ in range(6):
                    if not out.startswith("paused"):
                        break
                    out = await h(agent, kw)
            trace.append(f"{tname}({_short(kw)}): {out.splitlines()[0][:140] if out else ''}")
            return out
        return call

    logs: list[str] = []
    env: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "_tick": _tick, "args": dict(args), "parse": parse,
                           "failed": failed, "log": lambda *x: logs.append(" ".join(str(i) for i in x)[:300])}
    for p in sk.get("params") or []:
        env[p] = args.get(p)
    for t in TOOL_NAMES:
        env[t] = tool(t)
    t0 = time.time()
    ok, result, err = True, None, ""
    try:
        exec(_compile(sk["code"]), env)  # defines _main in env only; the code runs below, inside the limits
        result = await asyncio.wait_for(env["_main"](), SCRIPT_SECS)
    except asyncio.TimeoutError:
        ok, err = False, f"ran over {SCRIPT_SECS}s"
    except ScriptError as e:
        ok, err = False, str(e)
    except Exception as e:  # the serf's code: report it, don't crash the agent
        ok, err = False, f"{type(e).__name__}: {e}"
    if ok and isinstance(result, str) and failed(result):
        ok = False
    record_use(name, ok, time.time() - t0, err or (str(result)[:200] if not ok else ""), run=_run_id(agent))
    head = f"skill {name}: {'done' if ok else 'FAILED'} in {time.time() - t0:.0f}s, {state['calls']} tool calls"
    body = [head]
    if err:
        body.append(f"error: {err}")
    if result is not None:
        body.append(f"returned: {str(result)[:600]}")
    body += [f"log: {x}" for x in logs[-10:]]
    body += ["trace:"] + [f"  {x}" for x in trace[-15:]]
    return ok, "\n".join(body)


def _short(kw: dict) -> str:
    s = json.dumps(kw, separators=(",", ":"))
    return s if len(s) < 90 else s[:87] + "..."


def _run_id(agent: "Agent") -> str:
    return os.environ.get("SERF_RUN_ID", "") or getattr(agent.orch.cfg, "state_dir", Path("")).name
