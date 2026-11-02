"""The in-game wiki: "@serf how do I make plastic?" or "@serf what's on vulcanus?", answered in a few short lines told
only to the player who asked. The facts come from this game's own recipe data (Factorio 2.1, jev/data/recipes.json)
and the Factorio wiki (jev/knowledge.py, cached); the quick model (Sonnet by default) words the answer.
"""
from __future__ import annotations

import asyncio
import logging
import re

from . import knowledge
from .ratios import DATA

log = logging.getLogger("jev.wiki")

SYSTEM = """You answer a Factorio 2.1 (Space Age) player's question in at most 4 short lines of plain text, like a \
teammate who knows the game well: no markdown, no headings, no bullet lists. Numbers where they help (amounts, \
times, machine counts). The recipe data you get is this game's own (version 2.1): trust it over the wiki text where \
they differ. If neither covers the question, answer from what you know and say you're not sure."""
LINES, LINE_CHARS = 4, 240
LONG = """The answer goes in a window the player can scroll: up to 12 short paragraphs or lines of plain text, still \
no markdown. Cover what they'd need next (where it's made, what feeds it, ratios), not just the one fact."""


def _words(text: str) -> set[str]:
    ws = set(re.findall(r"[a-z0-9]+", text.lower()))
    return ws | {w[:-1] for w in ws if w.endswith("s") and len(w) > 3}  # "plates" finds iron-plate


def recipe_facts(question: str, limit: int = 4) -> list[dict]:
    """The recipes the question names (every word of the recipe's name is in it), most specific first, with the
    machines that make them."""
    words = _words(question)
    hits = [n for n in DATA["recipes"] if all(t in words for t in n.split("-") if t not in ("recipe",))]
    hits.sort(key=lambda n: -len(n.split("-")))
    out = []
    for n in hits[:limit]:
        r = DATA["recipes"][n]
        cats = r.get("categories") or [r.get("category")]
        machines = sorted(m for m, d in DATA["machines"].items() if set(d.get("categories") or []) & set(cats))
        out.append({"recipe": n, "seconds": r.get("energy"), "makes": r.get("products"),
                    "needs": r.get("ingredients"), "made_in": machines[:6]})
    return out


async def _ask(prompt: str, model: str, long: bool = False) -> str:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
    system = (SYSTEM.replace("in at most 4 short lines of plain text", "in plain text") + "\n\n" + LONG) if long \
        else SYSTEM
    opts = ClaudeAgentOptions(system_prompt=system, tools=[], allowed_tools=[], setting_sources=[], model=model,
                              max_turns=1)
    text = ""
    async for m in query(prompt=prompt, options=opts):
        if isinstance(m, AssistantMessage):
            text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
    return text


def lines(text: str) -> list[str]:
    """At most LINES chat lines of at most LINE_CHARS each, cut at word boundaries."""
    out = []
    for para in [x.strip() for x in text.splitlines() if x.strip()]:
        para = re.sub(r"^[-*#>\s]+", "", para)
        while para and len(out) < LINES:
            if len(para) <= LINE_CHARS:
                out.append(para)
                break
            cut = para.rfind(" ", 0, LINE_CHARS)
            cut = cut if cut > 40 else LINE_CHARS
            out.append(para[:cut].rstrip() + " ...")
            para = para[cut:].lstrip()
    return out[:LINES]


async def answer(question: str, model: str, timeout: float = 60, long: bool = False) -> list[str]:
    facts = recipe_facts(question)
    try:
        wiki = await asyncio.wait_for(asyncio.to_thread(knowledge.lookup, question), 20)
    except Exception as e:  # noqa: BLE001  (offline, or the wiki is down: the recipe data still answers a lot)
        log.debug("wiki lookup failed: %r", e)
        wiki = ""
    prompt = f"Question: {question}\n\nRecipe data (Factorio 2.1): {facts or 'none matched'}\n\n" \
             f"Wiki (2.0 era, may be out of date):\n{(wiki or 'nothing found')[:3500]}"
    text = await asyncio.wait_for(_ask(prompt, model, long), timeout)
    if long:  # for the window: paragraphs as written, markdown marks dropped
        return [re.sub(r"^[-*#>\s]+", "", x).strip() for x in text.splitlines() if x.strip()][:24]
    return lines(text)
