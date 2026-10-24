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
    lines += fix_first(a)
    bad = sorted(((k, v) for k, v in (a.get("groups") or {}).items() if v.get("n", 0) > v.get("working", 0)),
                 key=lambda kv: -(kv[1]["n"] - kv[1].get("working", 0)))
    if bad:
        lines.append("Not working, by what they make:")
        for k, v in bad[:groups]:
            at = v.get("at")
            where = f" e.g. at [gps={at[0]},{at[1]}]" if at else ""
            why = v.get("why") or v.get("why_other") or ""
            lacks = v.get("lacks") if isinstance(v.get("lacks"), dict) else {}
            short = ", ".join(f"{item} in {n}" for item, n in sorted(lacks.items(), key=lambda kv: -kv[1])[:4])
            lines.append(f"- {k}: {v['working']}/{v['n']} working, {v.get('starved', 0)} starved"
                         + (f" ({why}" + (f": lacking {short}" if short else "") + ")" if why and v.get("starved")
                            else "")
                         + f", {v.get('blocked', 0)} blocked" + (f", {v.get('other', 0)} {v.get('why_other')}"
                                                                if v.get("other") else "") + where)
        if len(bad) > groups:
            lines.append(f"- and {len(bad) - groups} more kinds")
    hf = a.get("hand_fed") or []
    if hf:
        lines.append(f"Chests filled by hand ({len(hf)}; each is a line that isn't automated): "
                     + "; ".join(f"[gps={c['at'][0]},{c['at'][1]}] {c['holds']}" for c in hf[:10]))
    ore = [g for g in (a.get("ore_left") or []) if isinstance(g, dict)]
    if ore:
        def left(g):
            amt = g.get("amount", 0)
            amount = f"{amt / 1000:.0f}k" if amt >= 1000 else f"{amt}"
            mins = g.get("minutes")
            when = (f"~{mins / 60:.1f} h" if mins and mins >= 120 else f"~{mins} min") if mins is not None else "?"
            return f"{g['ore']} at [gps={g['at'][0]},{g['at'][1]}]: {amount} under {g['drills']} drills, {when} at their rate"
        soon = [g for g in ore if g.get("minutes") is not None and g["minutes"] < 120]
        lines.append(("Ore under the drills (runs out soonest first; open new mines before a patch runs dry): "
                      if soon else "Ore under the drills: ") + "; ".join(left(g) for g in ore[:6]))
    dry = (a.get("status") or {}).get("no_minable_resources", 0)
    if dry:
        lines.append(f"{dry} drills stand on mined-out ground: move them onto ore or open a new patch.")
    gaps = a.get("pipe_gaps") or []
    if gaps:
        lines.append("Pipe lines broken by a gap (fluid on one side, an empty pipe just past it; a pipe in the gap "
                     "joins them): " + "; ".join(f"{g['fluid']} stops at [gps={g['at'][0]},{g['at'][1]}], {g['gap']} "
                                                 f"tile(s) short of [gps={g['to'][0]},{g['to'][1]}]" for g in gaps[:6]))
    lp = [x for x in (a.get("long_pipes") or []) if isinstance(x, dict)]
    if lp:
        lines.append("Pipelines too long to flow:")
        lines += ["- " + long_words(x) for x in lp[:4]]
    br = [b for b in (a.get("fluid_breaks") or []) if isinstance(b, dict)]
    if br:
        lines.append("Fluid lines behind stopped machines (followed pipe by pipe):")
        lines += ["- " + break_words(b) for b in br]
    lines.append(f"Belt tiles per machine {n['belts_per_machine']}, pipe tiles per machine {n['pipes_per_machine']}.")
    return "\n".join(lines)


ORE_PLATE = {"iron-ore": "iron-plate", "copper-ore": "copper-plate", "stone": "stone-brick"}


def fix_first(a: dict) -> list[str]:
    """Supply failures every chain downstream waits on, said first (p9 at 4.7% working: 42 of 66 iron furnaces
    without ore while its far iron drills sat blocked, and the manager kept building processing units)."""
    g = a.get("groups") or {}
    dry = int((a.get("status") or {}).get("no_minable_resources", 0))
    out = []
    for ore, plate in ORE_PLATE.items():
        mine, furn = g.get(f"mining {ore}") or {}, g.get(plate) or {}
        starved, n = int(furn.get("starved", 0)), int(furn.get("n", 0))
        if not n or starved < 3 or starved < 0.3 * n:
            continue
        blocked = int(mine.get("blocked", 0))
        at = mine.get("at")
        where = f", e.g. at [gps={at[0]},{at[1]}]" if at else ""
        if blocked >= 3:
            out.append(f"Fix first: {starved} of {n} {plate} furnaces have no {ore} while {blocked} {ore} drills are "
                       f"blocked with full outputs{where}: the ore isn't reaching the furnaces. Follow the ore belt from "
                       "those drills to where it stops or jams, and mend it before building anything new.")
        else:
            out.append(f"Fix first: {starved} of {n} {plate} furnaces have no {ore}"
                       + (f", and {dry} drills stand on mined-out ground" if dry else "")
                       + f": open a new {ore} mine (or more drills) feeding them before building anything new.")
    return out


def _gps(p) -> str:
    return f"[gps={p[0]},{p[1]}]"


def _members(ms: list, word: str) -> str:
    """'3 pumpjack (e.g. [gps=..] waiting_for_space_in_destination)' grouped by name."""
    if not ms:
        return ""
    by: dict[str, list] = {}
    for m in ms:
        by.setdefault(m["n"], []).append(m)
    parts = []
    for name, xs in by.items():
        st = [x.get("status") for x in xs if x.get("status") and x.get("status") != "working"]
        parts.append(f"{len(xs)} {name} (e.g. {_gps(xs[0]['p'])}" + (f", {st[0]}" if st else "") + ")")
    return f"{word} " + ", ".join(parts)


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def _end_words(d: dict, fluid: str | None = None) -> str:
    at = f"{d.get('n', 'pipe')} at {_gps(d['at'])}"
    toward = d.get("toward")
    nx, fu = d.get("next_to"), d.get("further")
    if d.get("kind") == "ghost":
        return f"an unbuilt ghost of a {d.get('n')} at {_gps(d['at'])}: the line is open there until it's built"
    if d.get("kind") == "lone pipe":
        return f"a lone {at} joined to nothing"
    if d.get("kind") == "underground, no exit":
        s = f"{at} goes underground heading {toward} and finds no exit"
        if fu:
            s += (f"; the next pipe-to-ground that way is {_n(fu['gap'], 'tile')} on at {_gps(fu['p'])}, facing "
                  f"{fu.get('dir')} (an exit for this one faces {toward})")
            if fu.get("fluid"):
                s += f" and holds {fu['fluid']}"
        return s
    s = f"{at} ends" + (f" facing {toward}" if toward else "")
    if nx:
        what = f"a {nx['n']} at {_gps(nx['p'])}"
        if nx.get("blocks"):
            return s + f"; {what} is in the way"
        if nx.get("fluid"):
            what += f" holding {nx['fluid']}"
        clash = fluid and nx.get("fluid") and nx["fluid"] != fluid
        return s + f"; {what} is right past it" + (": different fluids never join" if clash else " but not joined to it")
    if fu:
        held = f" holding {fu['fluid']}" if fu.get("fluid") else " (dry)"
        s += f"; the next {fu['n']} is {_n(fu['gap'], 'tile')} on at {_gps(fu['p'])}{held}: a gap"
        if fluid and fu.get("fluid") and fu["fluid"] != fluid:
            return s + f" (but it holds {fu['fluid']}, not {fluid}: joining them would mix fluids)"
        return s + (" (one pipe there joins them)" if fu["gap"] == 1 else "")
    return s + "; nothing within 8 tiles past it"


def line_words(net: dict, ends: int = 4, origin: str | None = None) -> str:
    """One fluid line from the mod's `pipes` walk: size, contents, what it joins, where it ends. origin = the kind of
    port the walk started from ('input': the machine there takes from the line; 'output': it feeds the line)."""
    size = [_n(net.get("pipes", 0), "pipe")]
    if net.get("tanks"):
        size.append(_n(net["tanks"], "tank"))
    if net.get("pumps"):
        size.append(_n(net["pumps"], "pump"))
    held = (f"holding {net['fluid']} ({net.get('fill', 0)}% full)" if net.get("fluid") else "dry")
    ext = net.get("extent")
    over = (f" from {_gps(ext[:2])} to {_gps(ext[2:])}" if ext and (ext[0] != ext[2] or ext[1] != ext[3]) else "")
    parts = [", ".join(size) + f" {held}{over}"]
    for key, word in (("sources", "fed by"), ("users", "feeding"), ("through", "passing through")):
        ms = net.get(key) or []
        if ms:
            n = net.get(key + "_n") or len(ms)
            parts.append(_members(ms, word) + (f" ({n} in all)" if n > len(ms) else ""))
    if not net.get("sources") and origin != "output":
        parts.append("no pump, pumpjack or machine output puts fluid on it")
    if not net.get("users") and not net.get("through") and origin not in ("input", "input-output"):
        parts.append("no machine takes from it")
    es = net.get("ends") or []
    total = net.get("ends_total", len(es))
    if es:
        more = total - min(len(es), ends)
        parts.append(f"{_n(total, 'open end')}: " + "; ".join(_end_words(d, net.get("fluid") or net.get("wanted"))
                                                              for d in es[:ends])
                     + (f"; and {more} more" if more > 0 else ""))
    elif net.get("pipes"):
        parts.append("no open ends")
    for ln in [x for x in (net.get("long") or []) if isinstance(x, dict)][:2]:
        parts.append(long_words(ln))
    if net.get("cut"):
        parts.append("(stopped walking after 6000 pieces)")
    return "; ".join(parts)


EXTENT = 320  # the mod's fluids.EXTENT


def long_words(ln: dict) -> str:
    """A fluid segment too long to flow (Factorio 2.0: one spanning more than 320 tiles fills but delivers nothing)."""
    what = f"{ln['pipes']} pipes" if ln.get("pipes") else "the pipes"
    held = f" of {ln['fluid']}" if ln.get("fluid") else ""
    return (f"{what}{held} from {_gps(ln['from'])} to {_gps(ln['to'])} form one segment {ln['span']} tiles long: "
            f"in Factorio 2.0 a segment longer than {EXTENT} tiles fills up but nothing comes out of its far end. "
            f"Put a powered pump in it at least every 300 tiles (each pump starts a new segment), or refine where "
            f"the crude is and belt the products back")


def break_words(b: dict) -> str:
    m = b.get("machine") or {}
    where = f"{m.get('n')} at {_gps(m['p'])}" if m.get("p") else str(m.get("n"))
    fl = b.get("fluid") or "fluid"
    net = b.get("line") or {}
    if b.get("why") == "missing":
        head = f"{where} lacks {fl}: the line into it is "
        net = {**net, "wanted": fl}
        tail = ""
        srcs = [m for m in (net.get("sources") or []) if isinstance(m, dict)]
        if srcs and any(m.get("status") in (None, "working", "normal") for m in srcs):
            tail = (f". A working source is on this line, so it's joined but too little comes through (more "
                    f"sources, or a pump partway along a long line)")
        elif srcs:
            tail = f". What feeds this line is stopped itself ({srcs[0].get('status')}): mend that first"
    else:
        head = f"{where} can't push its {fl} out: the line out of it is "
        tail = ""
        if net.get("users"):
            tail = ". Machines that use it are on this line, so the line is joined; they take less than it makes"
    return head + line_words(net, origin=(net.get('port') or {}).get('kind')) + tail
