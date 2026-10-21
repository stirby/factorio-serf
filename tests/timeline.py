"""Print a run's actor log as a compact timeline: python tests/timeline.py bench/runs/<run_id> [--full]"""
import json, sys
from pathlib import Path
d = Path(sys.argv[1]); full = "--full" in sys.argv
t0 = None
for l in open(d / "actor.jsonl"):
    r = json.loads(l); t0 = t0 or r["t"]; k = r["kind"]; ts = f"{r['t'] - t0:7.1f}"
    W = 2000 if full else 230
    if k == "thinker_tool":
        print(ts, "  TOOL", r["tool"], json.dumps(r["args"])[:W], "->", r["out"][:W // 2])
    elif k == "thinker_prompt":
        print(ts, "PROMPT", r["text"][:W].replace("\n", " | "))
    elif k == "thinker_turn":
        print(ts, "  TURN", f"{r['secs']}s ${r['cost']}", r.get("text", "")[:W // 2].replace("\n", " | "))
    elif k == "plan":
        print(ts, "  PLAN", json.dumps(r["plan"])[:W * 3])
    elif k == "act":
        print(ts, "   act", r["action"].get("op") if isinstance(r["action"], dict) else r["action"], r.get("ok"), f"{r.get('secs')}s", str(r.get("msg"))[:W // 2])
    elif k == "step":
        print(ts, "  step", r["i"], r["step"].get("do"), r.get("ok"), str(r.get("msg"))[:W // 2])
    else:
        print(ts, k, {kk: str(v)[:W // 2] for kk, v in r.items() if kk not in ("t", "kind")})
