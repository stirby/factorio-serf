#!/usr/bin/env python3
"""No-LLM check of the stamp tool: clear-area check, ghost placement, blocked-area refusal."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from instance import Instance  # noqa: E402

from crew import tools  # noqa: E402
from crew.board import Board  # noqa: E402
from crew.game import GameLink  # noqa: E402


class FakeAgent:
    def __init__(self, link, name):
        self.link, self.name = link, name
        self.board = Board(Path("/tmp/claude-1000") / "stamp-test-board.json")
        self.pending_jobs, self.finished = set(), {}
        self.last_position = None


async def main():
    with Instance(8, "stage-s3-steel-oil-ready") as inst:
        link = GameLink("127.0.0.1", inst.rcon_port, inst.password)
        await link.start()
        agent = FakeAgent(link, "claude-1")
        # find a clear 16x16 area near the agent
        me = await link.call("self", agent="claude-1")
        x0, y0 = int(me["position"][0]), int(me["position"][1])
        spot = None
        for r in range(10, 200, 6):
            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r)):
                b = await link.call("blockers", x1=x0 + dx, y1=y0 + dy, x2=x0 + dx + 16, y2=y0 + dy + 16)
                if not b["blockers"] and not b["water_tiles"] and b["trees_or_rocks"] == 0:
                    spot = (x0 + dx, y0 + dy)
                    break
            if spot:
                break
        print("clear spot", spot)
        out = await tools.t_stamp(agent, {"name": "red-science-5", "x": spot[0], "y": spot[1], "rotation": 0})
        print(out[:400])
        g = await link.call("ghosts", x=spot[0] + 7, y=spot[1] + 3, radius=20)
        print("ghosts there:", g["count"])
        ok1 = "stamped" in out and g["count"] >= 40
        out2 = await tools.t_stamp(agent, {"name": "red-science-5", "x": spot[0], "y": spot[1], "rotation": 0})
        ok2 = "isn't clear" in out2 or "blocked" in out2
        print("second stamp on same spot refused:", ok2, "|", out2[:160])
        print("PASS" if ok1 and ok2 else "FAIL")


asyncio.run(main())
