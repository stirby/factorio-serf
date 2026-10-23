"""The base's health in words: the mod's read-only `audit` op, summed up the way a player sizes up a base.

What matters is whether the base runs without anyone carrying things: machines working, what the rest lack, chests
someone has to fill by hand, and the science the labs actually get. (Both rocket worlds of 22 October made no
science left alone: docs/BUILD-LIKE-A-PLAYER.md.)
"""
from __future__ import annotations

SHORT = {"automation-science-pack": "red", "logistic-science-pack": "green", "military-science-pack": "military",
         "chemical-science-pack": "blue", "production-science-pack": "purple", "utility-science-pack": "yellow",
         "space-science-pack": "space"}


def numbers(a: dict) -> dict:
    """The scores: working share, starved/blocked shares, hand-fed chests, science per minute (total), belt and
    pipe tiles per machine."""
    m = max(int(a.get("machines") or 0), 1)
    g = (a.get("groups") or {}).values()
    working = sum(x.get("working", 0) for x in g)
    starved = sum(x.get("starved", 0) for x in g)
    blocked = sum(x.get("blocked", 0) for x in g)
    spm = sum((a.get("science_per_min") or {}).values())
    return {"machines": int(a.get("machines") or 0), "working_share": round(working / m, 3),
            "starved_share": round(starved / m, 3), "blocked_share": round(blocked / m, 3),
            "hand_fed_chests": len(a.get("hand_fed") or []), "spm": round(spm, 1),
            "belts_per_machine": round((a.get("belts") or 0) / m, 1),
            "pipes_per_machine": round((a.get("pipes") or 0) / m, 1)}


def words(a: dict, groups: int = 14) -> str:
    n = numbers(a)
    m = n["machines"]
    sci = a.get("science_per_min") or {}
    lines = [f"{round(n['working_share'] * m)} of {m} machines working ({n['working_share']:.0%}); "
             f"{n['starved_share']:.0%} starved of inputs, {n['blocked_share']:.0%} blocked by full outputs.",
             "Science used by labs per minute: " + (", ".join(f"{SHORT.get(k, k)} {v:g}" for k, v in sci.items())
                                                    or "none") + f" (labs working {a.get('labs_working', 0)} of "
                                                                 f"{a.get('labs', 0)})."]
    bad = sorted(((k, v) for k, v in (a.get("groups") or {}).items() if v.get("n", 0) > v.get("working", 0)),
                 key=lambda kv: -(kv[1]["n"] - kv[1].get("working", 0)))
    if bad:
        lines.append("Not working, by what they make:")
        for k, v in bad[:groups]:
            at = v.get("at")
            where = f" e.g. at [gps={at[0]},{at[1]}]" if at else ""
            why = v.get("why") or v.get("why_other") or ""
            lines.append(f"- {k}: {v['working']}/{v['n']} working, {v.get('starved', 0)} starved"
                         + (f" ({why})" if why and v.get("starved") else "")
                         + f", {v.get('blocked', 0)} blocked" + (f", {v.get('other', 0)} {v.get('why_other')}"
                                                                if v.get("other") else "") + where)
        if len(bad) > groups:
            lines.append(f"- and {len(bad) - groups} more kinds")
    hf = a.get("hand_fed") or []
    if hf:
        lines.append(f"Chests filled by hand ({len(hf)}; each is a line that isn't automated): "
                     + "; ".join(f"[gps={c['at'][0]},{c['at'][1]}] {c['holds']}" for c in hf[:10]))
    lines.append(f"Belt tiles per machine {n['belts_per_machine']}, pipe tiles per machine {n['pipes_per_machine']}.")
    return "\n".join(lines)
