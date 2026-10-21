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
    "new_job": "asks the character to do something in the game: build, fix, fetch, deliver, connect, automate, "
               "research, clear, move, check on something",
    "more_info": "adds detail to or corrects the job it is already doing (where, how, which, a constraint)",
    "question": "asks the character a question that needs an answer in words, without asking it to do anything",
    "stop": "tells the character to stop, cancel, or wait",
    "approval": "answers a question the character asked: yes, go ahead, your call, sounds good",
    "chatter": "thanks, praise, greetings, or talk that needs no action",
}

PLAYBOOKS = {
    "fix": {"what": "something that used to work has stopped, is slow, starving, out of fuel, without power, backed "
                    "up or broken, and the player wants it running again",
            "not_for": "building something new or expanding production"},
    "deliver": {"what": "bring a stated number of specific items to a chest or to the player",
                "not_for": "automating production of those items"},
    "plan": {"what": "anything else: build or automate something new, route belts or power somewhere, set up "
                     "mining, expand, design a layout, a puzzle",
             "not_for": None},
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
        "addressed": noul(f"Is `message` meant for `me` ({me}): it names {me}, says @all or everyone, or talks to "
                          "whoever is listening, rather than to another named player?"),
        "kind": choice("What is `message`?", KINDS),
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
