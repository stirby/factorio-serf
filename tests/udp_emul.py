"""Exercise the UDP permission path from RCON: every call goes through the mod's as_player op (the same guard and
client rules as a player's own app). python tests/udp_emul.py K"""
import asyncio, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
from dev import connect  # noqa: E402
from jev.actor import Actor  # noqa: E402
from jev.game import Game  # noqa: E402
from jev.rcon import GameError  # noqa: E402
from jev.typesafe import reader  # noqa: E402


class AsPlayer:
    port = 0  # looks like the UDP crew to Game.start

    def __init__(self, crew, pi=1):
        self.crew, self.pi = crew, pi

    async def call(self, op, timeout=30, **kw):
        r = await self.crew.call("as_player", timeout=timeout, player_index=self.pi, request={"op": op, **kw})
        if not r.get("ok"):
            raise GameError(r.get("error"))
        d = r.get("data")
        return {} if d == [] else d


async def main(k):
    g0 = await connect(k)
    g = Game(AsPlayer(g0.crew), "serf2")
    await g.start()
    d = Path("/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/udpemul")
    a = Actor(g, reader(log_path=d / "jev.jsonl"), d, "serf2", think=False)
    await a.start()
    print("started; items", len(a.items), "recipes", len(a.recipes))
    w = await a.world((51, 5), 16)
    print("scan ok:", len(w.ents), "faults", [f["kind"] for f in w.faults()])
    print("materials", (await a.materials())[:3])
    await g0.call("chat", player="otterplex", message="@serf2 what are you doing")
    await asyncio.sleep(5)
    print([json.loads(l) for l in open(d / "actor.jsonl")][-2:])
    await a.stop(); await g.stop()
asyncio.run(main(int(sys.argv[1])))
