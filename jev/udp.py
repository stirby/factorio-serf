"""The game link for a player's own serf app: localhost UDP, no server or RCON needed.

Factorio must be started with `--enable-lua-udp PORT` (it binds that port); the mod reads packets every tick
and answers to the port they came from. Works in single player and from a client in multiplayer (the request
becomes an input action, every peer runs it, only this machine sends the reply). Requests are answered while
the game runs: a paused single-player game answers nothing until it resumes.
Framing both ways (scripts/link.lua): b"CC1 <id> <part> <parts>\\n" + body chunk.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import socket

from .rcon import GameError, RconError

DEFAULT_PORT = 27200
CHUNK = 60000
SETUP_HINT = ("is Factorio running with the launch option `--enable-lua-udp {port}`, a game loaded (not the main "
              "menu, not paused) and the factorio-serf mod enabled?")


def _split(body: str) -> list[bytes]:
    """Chunks of at most CHUNK bytes, never splitting a character."""
    out, cur, size = [], [], 0
    for ch in body:
        b = ch.encode()
        if size + len(b) > CHUNK:
            out.append(b"".join(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    out.append(b"".join(cur))
    return out


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, owner: "UdpCrew"):
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        self.owner._received(data)

    def error_received(self, exc: Exception) -> None:  # e.g. ICMP port unreachable: nothing listens on the port
        self.owner._fail_all(RconError(f"UDP error: {exc!r}"))


class UdpCrew:
    """Same interface as rcon.Crew (connect, close, call) over localhost UDP."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
        self.host, self.port = host, port
        self._transport: asyncio.DatagramTransport | None = None
        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future] = {}
        self._parts: dict[str, dict[int, bytes]] = {}

    async def connect(self) -> None:
        await self.close()
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Proto(self),
                                                                 remote_addr=(self.host, self.port))
        try:  # room for a big reply; the OS caps it (default Linux: ~416 KB, which the mod's pacing stays under)
            self._transport.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        except OSError:
            pass
        try:
            await self.call("ping", timeout=5)
        except (RconError, asyncio.TimeoutError):
            await self.close()
            raise RconError(f"no answer on UDP {self.host}:{self.port}: " + SETUP_HINT.format(port=self.port))

    async def close(self) -> None:
        if self._transport:
            self._transport.close()
        self._transport = None
        self._fail_all(RconError("UDP link closed"))

    def _fail_all(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        self._parts.clear()

    def _received(self, data: bytes) -> None:
        head, _, chunk = data.partition(b"\n")
        try:
            tag, rid, i, n = head.decode().split(" ")
            i, n = int(i), int(n)
        except ValueError:
            return
        if tag != "CC1" or rid not in self._pending:
            return
        parts = self._parts.setdefault(rid, {})
        parts[i] = chunk
        if len(parts) < n:
            return
        del self._parts[rid]
        fut = self._pending.pop(rid)
        if not fut.done():
            fut.set_result(b"".join(parts[k] for k in range(1, n + 1)).decode(errors="replace"))

    async def call(self, op: str, timeout: float = 90, **kw):
        if not self._transport:
            raise RconError("UDP link not connected")
        kw["op"] = op
        rid = format(next(self._ids), "x")
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        chunks = _split(json.dumps(kw, separators=(",", ":")))
        for i, c in enumerate(chunks, 1):
            self._transport.sendto(f"CC1 {rid} {i} {len(chunks)}\n".encode() + c)
            if i % 3 == 0:
                await asyncio.sleep(0.02)  # like the mod: a few packets at a time
        try:
            raw = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            self._parts.pop(rid, None)
            raise RconError(f"no reply to {op} in {timeout:.0f}s (game paused or closed?)")
        try:
            reply = json.loads(raw)
        except json.JSONDecodeError:
            raise GameError(f"non-JSON reply to {op}: {raw[:300]}")
        if not reply.get("ok"):
            raise GameError(reply.get("error", "unknown error"))
        data = reply.get("data")
        return {} if data == [] else data
