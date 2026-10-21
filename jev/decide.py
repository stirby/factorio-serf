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
    "fix": {"what": "something that used to work has stopped, is slow, starving, out of fuel, without power, backed "
                    "up or broken, and the player only says WHAT is wrong, leaving how to fix it to the character",
            "not_for": "orders that say what to build or connect (belt X to Y, hook up power, build, automate), even "
                       "when they mention a problem",
            "examples": ["red science stopped at [gps]. can you get it going?", "the smelters ran out of coal",
                         "power keeps dipping, sort it out"]},
    "deliver": {"what": "bring a stated number of specific items to a chest or to the player",
                "not_for": "automating production of those items",
                "examples": ["I need 20 inserters in the chest at [gps]", "bring me 50 iron plates"]},
    "plan": {"what": "anything else: build or automate something new, belt or power something from A to B, set up "
                     "mining, expand, design a layout, follow someone, a puzzle",
             "examples": ["belt coal to the boiler from the drills", "automate gears here", "hook these up to the grid",
                          "follow me"]},
}


@dataclass
class ChatCall:
    addressed: float
    kind: str
    kind_conf: float
    playbook: str
    playbook_conf: float


async def chat(jev: Jev, me: str, speaker: str, message: str, doing: str | None, last_said: str | None) -> ChatCall:
    state = {"me": me, "speaker": speaker, "message": message,
             "what_i_am_doing": doing or "nothing", "my_last_chat_line": last_said or "none"}
    qs = {
        "addressed": noul(f"Is `message` meant for `me`: it names {me}, says @all or everyone, or talks to whoever "
                          "is listening, rather than to another named player or bot?"),
        "kind": choice("What does `message` do?", KINDS),
        "playbook": choice("If `message` asks for a job, which kind of job is it?", PLAYBOOKS),
    }
    a = await jev.ask(state, qs, kind="chat", meta={"speaker": speaker})
    return ChatCall(a["addressed"].p, a["kind"].choice, a["kind"].confidence, a["playbook"].choice,
                    a["playbook"].confidence)


async def fault(jev: Jev, complaint: str, faults: list[dict]) -> tuple[int | None, float, float]:
    """Pick the fault the complaint is about. Returns (index or None, confidence, p_any_fits)."""
    opts = {f"f{i}": f["text"] for i, f in enumerate(faults[:60])}
    state = {"player_said": complaint, "problems_found_near_there": list(opts.values())}
    qs = {
        "which": choice("Which problem in `problems_found_near_there` most likely causes what `player_said`?", opts),
        "any": noul("Does any problem in `problems_found_near_there` explain what `player_said`?"),
    }
    a = await jev.ask(state, qs, kind="fault")
    w = a["which"].choice
    return (int(w[1:]) if w else None), a["which"].confidence, a["any"].p


RECOVERY = {
    "retry": "try the same step again: the problem looks temporary (something moving, in the way for a moment, a "
             "timing issue)",
    "get_items": "the step failed because the character lacks an item: get the item first, then try again",
    "skip": "skip this step: the failure doesn't matter for the goal, or it is already done",
    "replan": "ask the planner for a new plan: the step itself is wrong (bad position, blocked spot, wrong item or "
              "direction, impossible as written)",
}


async def recovery(jev: Jev, goal: str, step_text: str, error: str, tries: int,
                   options: dict | None = None) -> tuple[str, float]:
    opts = options or RECOVERY
    state = {"goal": goal, "step": step_text, "error_message": error, "times_tried": tries}
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
    "assembly": {"what": "assemblers fed by inserters and belts: automate a product, make science, a mall",
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
    "none": {"what": "no building: a question, research, moving, delivering items, fixing a setting", "items": {}},
}


async def kit(jev: Jev, order: str) -> tuple[str, float]:
    opts = {k: v["what"] for k, v in KITS.items()}
    a = await jev.ask({"order": order}, {"kit": choice("Which building materials will doing `order` most likely "
                                                       "need?", opts)}, kind="kit")
    return a["kit"].choice, a["kit"].confidence


QUESTIONS = {
    "status": "what the character is doing, how the job is going, whether it's done",
    "where": "where the character is",
    "carrying": "what the character has in its inventory",
    "other": "anything else: about the base, production, plans, opinions, how to do something",
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
