"""The actor's decisions, each one a narrow Jev request over a small, semantic state that code prepares.

Code keeps control flow, exact checks and numbers; Jev answers the judgment calls:
  chat()      is this line for me, and what is it (new job / extra info / question / stop / chatter), and which
              fast playbook fits a new job (or none: the thinker plans it)
  fault()     which of the faults code found is the one the player is talking about
  recovery()  a step failed: retry, get the missing item first, skip it, or ask the thinker
  goal_met()  does the area now look like the plan's goal (when the plan has no machine-checkable expectations)
Each returns plain values plus the confidence, and the caller gates on confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .typesafe import Jev, choice, noul

KINDS = {
    "new_job": {"means": "asks for new work in the game", "examples": ["automate gears here", "build 8 furnaces",
                "the boiler is out of coal, fix it", "follow me", "bring me 50 plates"]},
    "more_info": {"means": "about the work in `what_i_am_doing`: a correction, a hint, a constraint, pointing out a "
                  "problem with it, or a push to keep going", "examples": ["put it on the other side",
                  "you see the problem there?", "not done yet, keep going", "use the logistic network for that"]},
    "question": {"means": "wants an answer in words, not work", "examples": ["what are you doing?",
                 "can you read my pings?", "how much copper do we make?"]},
    "stop": {"means": "stop, cancel, drop it, stop following", "examples": ["stop", "leave that one for now"]},
    "approval": {"means": "go-ahead or 'your call' (possibly with a hint) answering something the character asked",
                 "examples": ["yes do it", "your call", "your call on the layout, one is enough", "sounds good"]},
    "chatter": {"means": "thanks, praise, greetings, small talk, the speaker thinking out loud",
                "examples": ["thanks!", "gg", "how u doin", "nice work", "nvm I see it now"]},
}

PLAYBOOKS = {
    "fix": {"what": "machines or belts that exist have stopped, are slow, starving, out of fuel, without power, backed "
                    "up or broken, and the player wants them working again, including when they say to hook them up "
                    "to power, refuel them or unclog them",
            "not_for": "building something new, or moving items from one place to another with a new belt (belt X to "
                       "Y), even when they mention a problem",
            "examples": ["red science stopped at [gps]. can you get it going?", "the smelters ran out of coal",
                         "power keeps dipping, sort it out", "these assemblers have no power, hook them up to the grid"]},
    "deliver": {"what": "bring a stated number of specific items to a chest or to the player",
                "not_for": "automating production of those items",
                "examples": ["I need 20 inserters in the chest at [gps]", "bring me 50 iron plates"]},
    "plan": {"what": "anything else: build or automate something new, belt something from A to B, set up mining, "
                     "expand, design a layout, follow someone, research, a puzzle",
             "examples": ["belt coal to the boiler from the drills", "automate gears here", "build 8 furnaces",
                          "follow me"]},
}


@dataclass
class ChatCall:
    addressed: float
    kind: str
    kind_conf: float
    playbook: str
    playbook_conf: float
    multi: float = 0.0  # asks for two or more separate jobs at once


async def chat(jev: Jev, me: str, speaker: str, message: str, doing: str | None, last_said: str | None) -> ChatCall:
    state = {"me": me, "speaker": speaker, "message": message,
             "what_i_am_doing": doing or "nothing", "my_last_chat_line": last_said or "none"}
    qs = {
        "addressed": noul(f"Is `message` meant for `me`: it names {me}, says @all or everyone, or talks to whoever "
                          "is listening, rather than to another named player or bot?"),
        "kind": choice("What does `message` do?", KINDS),
        "playbook": choice("If `message` asks for a job, which kind of job is it?", PLAYBOOKS),
        "multi": noul("Does `message` ask for two or more separate jobs at once?",
                      "yes: 'make gears here and research solar', 'fix the boiler, then belt coal to it'",
                      "no: one job, however many parts it has ('8 furnaces and a belt to the chest' is one build; "
                      "'plates please, off that belt, a couple of furnaces' and 'gears off the belt, 3 assemblers, into "
                      "chests' are one build each: the machines make the product)"),
    }
    a = await jev.ask(state, qs, kind="chat", meta={"speaker": speaker})
    return ChatCall(a["addressed"].p, a["kind"].choice, a["kind"].confidence, a["playbook"].choice,
                    a["playbook"].confidence, a["multi"].p)


async def fault(jev: Jev, complaint: str, faults: list[dict]) -> tuple[int | None, float, float, float]:
    """Pick the fault the complaint is about. Returns (index or None, confidence, p_any_fits, p_wants_everything_fixed)."""
    opts = {f"f{i}": f["text"] for i, f in enumerate(faults[:60])}
    state = {"player_said": complaint, "problems_found_near_there": list(opts.values())}
    qs = {
        "which": choice("Which problem in `problems_found_near_there` most likely causes what `player_said`?", opts),
        "any": noul("Does any problem in `problems_found_near_there` explain what `player_said`?"),
        "all": noul("Does `player_said` ask to get the whole setup there working properly, rather than one "
                    "specific thing?",
                    "yes: 'science is really slow there, look at it and get it running properly', 'my sites stopped, "
                    "get them all running', 'sort it all out'",
                    "no: 'the boiler keeps running out of coal', 'that belt is backwards', 'power the assemblers'"),
    }
    a = await jev.ask(state, qs, kind="fault")
    w = a["which"].choice
    return (int(w[1:]) if w else None), a["which"].confidence, a["any"].p, a["all"].p


RECOVERY = {
    "retry": {"when": "the problem is temporary: the character itself or something moving was in the way, it timed "
                      "out, it got stuck on the way; trying again can work",
              "not_when": "the message says something doesn't exist or can't be done"},
    "get_items": {"when": "the character lacks an item that can still be fetched or crafted",
                  "not_when": "the message says no chest has it and it can't be hand-crafted"},
    "skip": {"when": "the step is already done or no longer needed: already researched, already built, the thing "
                     "to remove is already gone"},
    "replan": {"when": "the step can't work as written: wrong or blocked position, impossible item, no path, "
                       "too far, a tech that unlocks another way, nothing exists to use"},
}


def failure_facts(msg: str) -> dict:
    """Exact facts code reads off a failure message, so Jev doesn't have to parse them."""
    m = (msg or "").lower()
    blockers = re.findall(r"blocked by ([a-z0-9-]+)@", m)
    return {"blocked_only_by_the_character": bool(blockers) and all(b in ("character", "entity-ghost")
                                                                     for b in blockers) and "character" in blockers,
            "timed_out": "timed out" in m or "stuck at" in m,
            "already_done": "already" in m,
            "thing_to_remove_is_gone": m.startswith("nothing minable at"),
            "item_exists_nowhere": "no chest or machine output" in m and "can't hand-craft" in m}


async def recovery(jev: Jev, goal: str, step_text: str, error: str, tries: int,
                   options: dict | None = None) -> tuple[str, float]:
    opts = options or RECOVERY
    state = {"goal": goal, "step": step_text, "error_message": error, "times_tried": tries,
             "facts_from_code": failure_facts(error)}
    a = await jev.ask(state, {"next": choice("The `step` failed with `error_message`. What should the character do "
                                             "next?", opts)}, kind="recovery")
    return a["next"].choice, a["next"].confidence


async def goal_met(jev: Jev, goal: str, area: dict) -> float:
    a = await jev.ask({"goal": goal, "area_now": area},
                      {"met": noul("Does `area_now` show that `goal` is achieved and running on its own?")},
                      kind="goal_met")
    return a["met"].p


async def which_item(jev: Jev, phrase: str, candidates: list[str]) -> tuple[str, float]:
    opts = {c: None for c in candidates[:255]}
    a = await jev.ask({"player_wrote": phrase}, {"item": choice("Which item does `player_wrote` mean?", opts)},
                      kind="item")
    return a["item"].choice, a["item"].confidence


KITS = {
    "assembly": {"what": "assemblers fed by inserters and belts: automate or make any product (gears, circuits, "
                         "science, inserters...), a mall",
                 "items": {"assembling-machine-2": 4, "assembling-machine-1": 4, "inserter": 12, "transport-belt": 40,
                           "small-electric-pole": 10, "iron-chest": 3, "underground-belt": 4}},
    "smelting": {"what": "furnaces: smelt ore into plates or steel, a smelter column",
                 "items": {"stone-furnace": 8, "inserter": 16, "transport-belt": 40, "small-electric-pole": 8,
                           "iron-chest": 2}},
    "power": {"what": "more electricity: boilers, steam engines, offshore pump, poles",
              "items": {"boiler": 2, "steam-engine": 4, "offshore-pump": 1, "pipe": 10, "small-electric-pole": 8,
                        "inserter": 2}},
    "mining": {"what": "mine an ore patch with drills and belt the ore somewhere",
               "items": {"electric-mining-drill": 8, "transport-belt": 60, "small-electric-pole": 10,
                         "underground-belt": 4}},
    "belts": {"what": "route a belt or connect belts from one place to another",
              "items": {"transport-belt": 60, "underground-belt": 6, "splitter": 2, "inserter": 2}},
    "none": {"what": "no building: a question, research, moving, delivering items, breaking rocks or trees by hand, "
                     "fixing a setting", "items": {}},
}


async def kit(jev: Jev, order: str) -> tuple[str, float]:
    opts = {k: v["what"] for k, v in KITS.items()}
    a = await jev.ask({"order": order}, {"kit": choice("Which building materials will doing `order` most likely "
                                                       "need?", opts)}, kind="kit")
    return a["kit"].choice, a["kit"].confidence


QUESTIONS = {
    "status": "what the character is doing, how the job is going, whether it's done",
    "where": {"what": "where the character itself is right now", "not_for": "where things in the world are "
              "(ore, machines, other players)"},
    "carrying": "what the character has in its own inventory",
    "other": "anything else: where things are, the base, production, plans, opinions, how to do something",
}


async def question_type(jev: Jev, message: str) -> tuple[str, float]:
    a = await jev.ask({"question": message}, {"type": choice("What does `question` ask about?", QUESTIONS)},
                      kind="question")
    return a["type"].choice, a["type"].confidence


async def scope(jev: Jev, order: str) -> float:
    """Probability the order is about many places spread over a wide area (not one spot)."""
    a = await jev.ask({"order": order}, {"wide": noul(
        "Does `order` talk about several separate setups or places spread over a wide area (e.g. 'all my furnace "
        "setups around here', 'they're spread out'), rather than one spot?")}, kind="scope")
    return a["wide"].p


async def same_job(jev: Jev, job: str, message: str) -> float:
    """Probability the message is about that job (details, corrections, additions), not another job or subject (live
    test: "break all the rocks... can you use construction bots?" joined the queued roboport order)."""
    a = await jev.ask({"queued_job": job, "message": message}, {"same": noul(
        "Is `message` more about `queued_job` (details, corrections or additions for that same job), rather than "
        "about a different job or another subject?")}, kind="same_job")
    return a["same"].p


async def changes_plan(jev: Jev, doing: str, message: str) -> float:
    """Probability the message asks to change how/where the current job is done (so the plan must change)."""
    a = await jev.ask({"current_job": doing, "message": message}, {"change": noul(
        "Does `message` ask to change how, where or what is being built for `current_job` (a different place, "
        "side, item, amount or method), rather than just commenting, encouraging or asking for status?")},
        kind="changes_plan")
    return a["change"].p


async def not_done(jev: Jev, job: str, message: str) -> float:
    """Probability the message says the finished job isn't actually done or something about it is still wrong."""
    a = await jev.ask({"finished_job": job, "message": message}, {"not_done": noul(
        "Does `message` say that `finished_job` is not actually done, not working, or still has a problem to fix "
        "(rather than reporting progress, confirming it works, or chatting)?")}, kind="not_done")
    return a["not_done"].p


async def trouble(jev: Jev, conditions: list[str], area: dict) -> list[float]:
    """For each watched condition (words from the planner), the probability `area` shows it now."""
    qs = {f"w{i}": noul(f"Does `area` show this problem: {c}?") for i, c in enumerate(conditions[:20])}
    a = await jev.ask({"area": area}, qs, kind="watch")
    return [a[f"w{i}"].p for i in range(len(qs))]


async def research(jev: Jev, order: str, techs: list) -> tuple[str | None, float]:
    """Which of the techs that can be researched now (names, or the techs call's dicts with what they unlock) does
    `order` ask for (None: none of them, or not a research order)? Returns the tech and its probability."""
    opts = {}
    for t in techs[:240]:
        name = t if isinstance(t, str) else t["name"]
        un = [] if isinstance(t, str) else (t.get("unlocks") or [])
        opts[name] = name.replace("-", " ") + (f" (unlocks {', '.join(u.replace('-', ' ') for u in un[:4])})"
                                               if un else "")
    opts["none_of_these"] = "the order doesn't ask to research one of these (another tech, several, or 'whatever helps')"
    a = await jev.ask({"order": order}, {
        "tech": choice("Which research does `order` ask to start?", opts),
        "is_research": noul("Does `order` ask to start or queue a research (a technology)?"),
        "several": noul("Does `order` ask for two or more different researches?"),
    }, kind="research")
    t = a["tech"].choice
    if t == "none_of_these" or a["is_research"].p < 0.7 or a["several"].p >= 0.5:
        return None, 0.0
    return t, float(a["tech"].probs.get(t) or 0)


UPGRADES = {"fast-transport-belt": "red belts (fast transport belt), with their undergrounds and splitters",
            "express-transport-belt": "blue belts (express transport belt)",
            "assembling-machine-2": "assembler 2s (assembling machine 2)",
            "assembling-machine-3": "assembler 3s (assembling machine 3)",
            "steel-furnace": "steel furnaces", "fast-inserter": "fast inserters",
            "medium-electric-pole": "medium electric poles", "steel-chest": "steel chests",
            "none_of_these": "not an upgrade order, or something else"}


async def upgrade(jev: Jev, order: str) -> tuple[str | None, float, float]:
    """An order to swap buildings for a better tier: (into, probability, p_whole_belt_line)."""
    a = await jev.ask({"order": order}, {
        "into": choice("What does `order` ask to replace things with (swap or upgrade to)?", UPGRADES),
        "line": noul("Does `order` mean a whole belt line (rather than the buildings in one spot)?"),
    }, kind="upgrade")
    t = a["into"].choice
    if t == "none_of_these":  # (the actor only asks when the order says upgrade, swap, replace or "in place of")
        return None, 0.0, 0.0
    return t, float(a["into"].probs.get(t) or 0), a["line"].p
