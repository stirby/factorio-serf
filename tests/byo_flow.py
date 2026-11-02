#!/usr/bin/env python3
"""Bring your own serf, on a test slot, as a player's own app sees it (its calls go through the mod's as_player op,
the same guard and client rules as over UDP):
- an app with no serf in the world waits for /serf add, and takes a free name: "serf" belongs to another app here,
  so it's "<player>-serf", next to the player;
- another player's lines never reach it (no model call), and naming it gets them one note in chat;
- the owner's "@serf settings" is answered by code;
- a restarted app takes its serf over without /serf add.

    .venv/bin/python tests/byo_flow.py K      # a running test slot whose world has a player 1
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from dev import connect  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.cli import own_serf  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.quick_reader import reader  # noqa: E402
from jev.rcon import GameError  # noqa: E402

FAILS: list[str] = []


class AsPlayer:
    """A player's own app, over RCON: each call goes through the mod's as_player op (as in tests/udp_emul.py)."""
    port = 0  # looks like the UDP crew to Game

    def __init__(self, crew, pi=1):
        self.crew, self.pi = crew, pi

    async def call(self, op, timeout=30, **kw):
        r = await self.crew.call("as_player", timeout=timeout, player_index=self.pi, request={"op": op, **kw})
        if not r.get("ok"):
            raise GameError(r.get("error"))
        d = r.get("data")
        return {} if d == [] else d

# what the mod's /serf add pushes to the player's app (control.lua), pushed the same way through eval
ADD = """
local p = game.get_player(1)
storage.feed_seq = storage.feed_seq + 1
table.insert(storage.feed, { seq = storage.feed_seq, kind = "event", to = "p1", data = { type = "add", player = p.name,
  player_index = 1, position = { p.position.x + 2, p.position.y }, surface = p.surface.name, tick = game.tick } })
return p.name
"""


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)


def logged(d: Path, kind: str) -> list[dict]:
    p = d / "actor.jsonl"
    return [r for r in map(json.loads, p.read_text().splitlines()) if r.get("kind") == kind] if p.exists() else []


async def main(k: int) -> int:
    g0 = await connect(k)
    for a in (await g0.call("list")).get("agents") or []:  # a clean slate on this copy
        await g0.call("despawn", agent=a["name"])
    await g0.call("spawn", name="serf", client="rcon", near_player=None)  # "serf" is another app's

    g = Game(AsPlayer(g0.crew), "serf")
    await g.start(spawn=False)
    check("the app knows whose it is", g.you and g.client == "p1", (g.you, g.client))
    task = asyncio.create_task(own_serf(g, None))
    await asyncio.sleep(2)
    check("with no serf of its own it waits for /serf add", not task.done())
    player = (await g0.call("eval", code=ADD)).get("result")
    await asyncio.wait_for(task, 30)
    mine = [a for a in (await g0.call("list")).get("agents") or [] if a["name"] == g.name]
    check("/serf add brings one in, named <player>-serf since serf is taken", g.name == f"{player}-serf" and mine
          and mine[0].get("client") == "p1" and mine[0].get("owner") == player, (g.name, mine))

    d = Path(tempfile.mkdtemp(prefix="byo-"))
    act = Actor(g, reader(log_path=d / "quick.jsonl"), d, g.name, think=False)
    await act.start()
    await g0.call("chat", player="kyle", message="@serf build me a red science line")
    await g0.call("chat", player="kyle", message=f"@{g.name} bring me 50 gears")
    await g0.call("chat", player=player, message="@serf settings")
    await asyncio.sleep(4)
    chats = [r for r in logged(d, "chat")]
    check("another player's lines never reach the reader", not any(r.get("speaker") == "kyle" for r in chats), chats)
    says = [r["text"] for r in logged(d, "say")]
    check("naming someone else's serf gets one note, in chat to them", sum(s.startswith("@kyle ") for s in says) == 1,
          says)
    check("the owner's @serf settings is answered by code", any("effort" in s for s in says), says)
    await act.stop()
    await g.stop()

    g2 = Game(AsPlayer(g0.crew), "serf")
    await g2.start(spawn=False)
    await asyncio.wait_for(own_serf(g2, None), 15)
    check("a restarted app takes its serf over without /serf add", g2.name == f"{player}-serf", g2.name)
    await g2.stop()
    print(f"\n{'ALL OK' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]))))
