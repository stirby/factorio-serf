"""Per run: seconds from the order to the actor's 'done' (first order), Opus seconds, plans, and the split of the
actor's time (thinking wait, stocking, steps, verifying). python tests/speed.py <tag> ..."""
import json, sys, glob
from pathlib import Path
for tag in sys.argv[1:]:
    for d in sorted(glob.glob(f"bench/runs/*-{tag}*/")):
        p = Path(d) / "actor.jsonl"
        if not p.exists():
            continue
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        res = json.loads((Path(d) / "result.json").read_text()) if (Path(d) / "result.json").exists() else {}
        o = next((r for r in rows if r["kind"] == "order"), None)
        e = next((r for r in rows if r["kind"] == "order_end"), None)
        think = sum(r.get("secs", 0) for r in rows if r["kind"] == "thinker_turn")
        stock = sum(r.get("secs", 0) for r in rows if r["kind"] == "stock")
        acts = sum(r.get("secs", 0) or 0 for r in rows if r["kind"] == "act")
        name = Path(d).name.split("-", 2)[2].rsplit("-", 2)[0]
        print(f"{name:22} {'OK' if res.get('success') else '--'} order->end {e['secs'] if e else '-':>6}s "
              f"status={e['status'] if e else '-':9} plans={e['plans'] if e else '-'} think={think:5.0f}s "
              f"stock={stock:4.0f}s acts={acts:5.0f}s")
