"""Per-player serf apps: the UDP framing, and routing/ownership in the mod. No model calls.

  .venv/bin/python tests/test_udp.py [instance=9]      # framing (no server) + routing (scratch s3 instance)
  .venv/bin/python tests/test_udp.py --framing-only

The real UDP path needs a game client (single player, or a client in multiplayer): a headless 2.0.77 server
crashes when a Lua UDP packet arrives, so the in-game part sends requests over RCON through `as_player`, which runs
them exactly as a player's app would (same dispatch, same guards), minus the socket.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crew.rcon import Crew, GameError, Rcon  # noqa: E402
from crew.udp import CHUNK, UdpCrew  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        FAILS.append(what)


class FakeGame(asyncio.DatagramProtocol):
    """Speaks scripts/link.lua's framing: reassembles requests, answers {ok, data: {echo, big}} in chunks of CHUNK
    bytes cut on character boundaries (like link.lua's cut)."""

    def __init__(self):
        self.parts: dict[str, dict[int, bytes]] = {}
        self.max_packet = 0

    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        self.max_packet = max(self.max_packet, len(data))
        head, _, body = data.partition(b"\n")
        _, rid, i, n = head.decode().split(" ")
        got = self.parts.setdefault(rid, {})
        got[int(i)] = body
        if len(got) < int(n):
            return
        req = json.loads(b"".join(got[k] for k in range(1, int(n) + 1)).decode())
        del self.parts[rid]
        reply = json.dumps({"ok": True, "data": {"echo": len(req.get("pad", "")), "big": "ü" * req.get("want", 0)}},
                           ensure_ascii=False).encode()
        chunks, i0 = [], 0
        while i0 < len(reply):
            i1 = min(len(reply), i0 + CHUNK)
            while i1 < len(reply) and 0x80 <= reply[i1] < 0xC0:
                i1 -= 1
            chunks.append(reply[i0:i1])
            i0 = i1
        asyncio.get_running_loop().create_task(self._send(rid, chunks, addr))

    async def _send(self, rid, chunks, addr):
        for k, c in enumerate(chunks, 1):  # paced like link.lua: 3 packets per 1/60 s tick
            self.t.sendto(f"CC1 {rid} {k} {len(chunks)}\n".encode() + c, addr)
            if k % 3 == 0:
                await asyncio.sleep(1 / 60)


async def framing() -> None:
    loop = asyncio.get_running_loop()
    t, game = await loop.create_datagram_endpoint(FakeGame, local_addr=("127.0.0.1", 0))
    port = t.get_extra_info("sockname")[1]
    u = UdpCrew(port)
    await u.connect()
    d = await u.call("x", pad="é" * 70000, want=500000)  # 140 KB request, 1 MB reply
    check(d["echo"] == 70000, "multi-packet request reassembled (split on characters)")
    check(d["big"] == "ü" * 500000, "multi-packet reply reassembled")
    check(game.max_packet <= CHUNK + 40, f"every packet fits a localhost datagram ({game.max_packet} bytes)")
    import socket
    u._transport.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 106496)  # stock Linux
    d = await u.call("x", want=500000, timeout=10)
    check(d["big"] == "ü" * 500000, "1 MB reply survives a stock-Linux socket buffer (208 KB)")
    rs = await asyncio.gather(*(u.call("x", pad="a" * n) for n in range(20)))
    check([r["echo"] for r in rs] == list(range(20)), "20 concurrent calls each get their own reply")
    await u.close()
    t.close()
    dead = UdpCrew(port)
    try:
        await dead.connect()
        check(False, "connect to a closed port fails")
    except Exception as e:
        check("enable-lua-udp" in str(e), "closed port: error says how to set Factorio up")


async def routing(k: int) -> None:
    from instance import Instance
    with Instance(k, "stage-s3-steel-oil-ready") as inst:
        rc = Crew(Rcon(inst.host, inst.rcon_port, inst.password))
        await rc.connect()

        async def as_player(pi: int, op: str, **kw):
            r = await rc.call("as_player", player_index=pi, request={"op": op, **kw})
            if not r.get("ok"):
                raise GameError(r.get("error"))
            return {} if r.get("data") == [] else r.get("data")

        async def expect_error(coro, needle: str, what: str) -> None:
            try:
                await coro
                check(False, what + " (no error)")
            except GameError as e:
                check(needle in str(e), f"{what}: {e}")

        players = (await rc.call("eval", code="local t = {} for _, p in pairs(game.players) do "
                                              "t[#t + 1] = p.index end return t"))["result"] or []
        pi = players[0] if players else None
        check(pi is not None, f"the stage save has a player to act as ({players})")

        p1 = await as_player(pi, "poll")
        check(p1.get("client") == f"p{pi}" and bool(p1.get("you")), f"app identity: {p1.get('client')} / {p1.get('you')}")
        await rc.call("poll", client="opA")
        await rc.call("poll", client="opB")
        await expect_error(as_player(pi, "eval", code="return 1"), "operator", "an app can't eval")
        await expect_error(as_player(pi, "chat", player="x", message="hi"), "operator", "an app can't inject chat")

        # Chat reaches every orchestrator once, each from its own cursor.
        await rc.call("chat", player="tester", message="hello all")
        msgs = lambda d: [c["message"] for c in d.get("chat") or []]  # noqa: E731
        a, b, u = (await rc.call("poll", client="opA"), await rc.call("poll", client="opB"),
                   await as_player(pi, "poll"))
        check(msgs(a) == msgs(b) == msgs(u) == ["hello all"], f"chat fan-out: {msgs(a)} {msgs(b)} {msgs(u)}")
        check(not msgs(await rc.call("poll", client="opA")), "no repeat on the next poll")

        # Ownership: results go to the agent's orchestrator only; nobody else can drive it.
        await rc.call("spawn", name="t-a", client="opA", starter_kit=False)
        lst = {x["name"]: x for x in (await rc.call("list"))["agents"]}
        check(lst["t-a"].get("client") == "opA", f"agent records its orchestrator: {lst['t-a'].get('client')}")
        await rc.call("act", agent="t-a", actions=[{"op": "wait", "seconds": 0.1}])
        await asyncio.sleep(1)
        b, a = await rc.call("poll", client="opB"), await rc.call("poll", client="opA")
        check("t-a" not in (b.get("results") or {}) and "t-a" in (a.get("results") or {}),
              "job results go only to the agent's orchestrator")
        await expect_error(as_player(pi, "act", agent="t-a", actions=[{"op": "wait"}]), "someone else",
                           "an app can't drive another orchestrator's agent")
        await expect_error(as_player(pi, "spawn", name="t-a"), "taken", "an app can't take a used name")

        # A player's own serf: owner set, cap enforced, theirs to drive.
        s = await as_player(pi, "spawn", name="t-mine")
        lst = {x["name"]: x for x in (await rc.call("list"))["agents"]}
        check(lst["t-mine"].get("client") == f"p{pi}" and lst["t-mine"].get("owner") == p1["you"],
              f"app's serf is owned by its player: {lst['t-mine'].get('client')} {lst['t-mine'].get('owner')}")
        check(bool(await as_player(pi, "act", agent="t-mine", actions=[{"op": "wait", "seconds": 0.1}])),
              "an app drives its own serf")
        await as_player(pi, "spawn", name="t-mine2")
        await expect_error(as_player(pi, "spawn", name="t-mine3"), "allows 2", "serfs-per-player cap (2)")
        nested = await rc.call("as_player", player_index=pi, request={"op": "as_player", "request": {"op": "eval"}})
        check(not nested.get("ok"), f"an app can't use as_player: {nested.get('error')}")

        # /serf add arrives as an event for that player's app only.
        await rc.call("eval", code="storage.feed_seq = storage.feed_seq + 1 "
                                   "table.insert(storage.feed, {seq = storage.feed_seq, kind = 'event', "
                                   f"data = {{type = 'add', player = 'x'}}, to = 'p{pi}'}})")
        adds = lambda d: [e for e in d.get("events") or [] if e.get("type") == "add"]  # noqa: E731
        a, u = await rc.call("poll", client="opA"), await as_player(pi, "poll")
        check(len(adds(u)) == 1 and not adds(a), "an add event reaches only its player's app")
        await rc.close()


async def main() -> None:
    await framing()
    if "--framing-only" not in sys.argv:
        k = next((int(x) for x in sys.argv[1:] if x.isdigit()), 9)
        await routing(k)
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
