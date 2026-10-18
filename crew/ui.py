"""Console output: a readable live log of what each agent is thinking and doing."""
from __future__ import annotations

import json
import os
import sys
import time

COLORS = [208, 75, 113, 220, 141, 80, 203, 179]
_assigned: dict[str, int] = {}
VERBOSE = os.environ.get("CREW_VERBOSE") == "1"
_tty = sys.stdout.isatty()


def _c(code: int, s: str) -> str:
    return f"\x1b[38;5;{code}m{s}\x1b[0m" if _tty else s


def _dim(s: str) -> str:
    return f"\x1b[2m{s}\x1b[0m" if _tty else s


def _who(name: str) -> str:
    if name not in _assigned:
        _assigned[name] = COLORS[len(_assigned) % len(COLORS)]
    return _c(_assigned[name], f"{name:>9}")


def _ts() -> str:
    return _dim(time.strftime("%H:%M:%S"))


def _short(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def info(msg: str) -> None:
    print(f"{_ts()} {_dim('     crew')} {msg}", flush=True)


def human(player: str, msg: str) -> None:
    print(f"{_ts()} {_c(255, f'{player:>9}')} \x1b[1m{msg}\x1b[0m" if _tty else f"{_ts()} {player:>9} {msg}", flush=True)


def chat(agent: str, msg: str) -> None:
    print(f"{_ts()} {_who(agent)} 💬 {msg}", flush=True)


def status(agent: str, text: str, mode: str) -> None:
    print(f"{_ts()} {_who(agent)} {_dim('status')} {text} {_dim('[' + mode + ']')}", flush=True)


def turn_start(agent: str, events: list[str]) -> None:
    print(f"{_ts()} {_who(agent)} {_dim('wakes:')} {_short(' | '.join(events), 160)}", flush=True)


def turn_end(agent: str, secs: float, stats, total: float) -> None:
    err = f" error={stats.error}" if stats.error else ""
    print(f"{_ts()} {_who(agent)} {_dim(f'turn done {secs:.0f}s, {stats.steps} tool calls, ~${stats.cost_usd:.3f} (session ~${total:.2f}){err}')}",
          flush=True)


def thought(agent: str, text: str) -> None:
    print(f"{_ts()} {_who(agent)} {_dim('thinks')} {_short(text, 220 if not VERBOSE else 2000)}", flush=True)


def tool(agent: str, name: str, args: dict) -> None:
    if name == "act":
        acts = args.get("actions") or []
        if isinstance(acts, str):
            try:
                acts = json.loads(acts)
            except json.JSONDecodeError:
                acts = []
        desc = "; ".join(_short(" ".join(f"{v}" if k == "op" else f"{k}={v}" for k, v in a.items()), 60)
                         for a in acts[:6])
        if len(acts) > 6:
            desc += f"; +{len(acts) - 6} more"
        print(f"{_ts()} {_who(agent)} ⚙  act [{desc}]", flush=True)
    elif name in ("say", "status"):
        return
    else:
        arg = _short(json.dumps(args, separators=(",", ":")), 80) if args else ""
        print(f"{_ts()} {_who(agent)} 🔎 {name} {_dim(arg)}", flush=True)


def tool_result(agent: str, name: str, out: str) -> None:
    if name in ("act", "wait") or VERBOSE:
        for line in out.splitlines()[:8]:
            if line.startswith("you:") and not VERBOSE:
                continue
            print(f"{_ts()} {_who(agent)}    {_dim('↳')} {_short(line, 200)}", flush=True)
