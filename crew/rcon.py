"""Minimal async Source RCON client, plus the JSON call wrapper for the claude-crew mod."""
from __future__ import annotations

import asyncio
import json
import struct

AUTH, AUTH_RESPONSE, EXEC = 3, 2, 2


class RconError(Exception):
    pass


class GameError(Exception):
    """The mod answered {ok: false, error: ...}."""


class Rcon:
    def __init__(self, host: str, port: int, password: str):
        self.host, self.port, self.password = host, port, password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._id = 0

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=10)
        await self._send(AUTH, self.password)
        while True:
            rid, typ, _ = await self._recv()
            if typ == AUTH_RESPONSE:
                break
        if rid == -1:
            raise RconError("RCON auth failed (wrong password?)")

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = self._writer = None

    async def _send(self, typ: int, body: str) -> int:
        self._id = (self._id + 1) % 2**31
        data = struct.pack("<ii", self._id, typ) + body.encode() + b"\x00\x00"
        assert self._writer
        self._writer.write(struct.pack("<i", len(data)) + data)
        await self._writer.drain()
        return self._id

    async def _recv(self) -> tuple[int, int, str]:
        assert self._reader
        (size,) = struct.unpack("<i", await self._reader.readexactly(4))
        data = await self._reader.readexactly(size)
        rid, typ = struct.unpack("<ii", data[:8])
        return rid, typ, data[8:-2].decode(errors="replace")

    async def command(self, cmd: str, timeout: float = 30) -> str:
        """Run a console command and return its output (Factorio replies in one packet)."""
        async with self._lock:
            if not self._writer:
                await self.connect()
            try:
                rid = await self._send(EXEC, cmd)
                while True:
                    r, _, body = await asyncio.wait_for(self._recv(), timeout)
                    if r == rid:
                        return body
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
                await self.close()
                raise RconError(f"RCON connection lost: {e!r}") from e


class Crew:
    """Typed-ish access to the mod's `/crew <json>` API."""

    def __init__(self, rcon: Rcon):
        self.rcon = rcon

    async def call(self, op: str, **kw):
        kw["op"] = op
        raw = await self.rcon.command("/crew " + json.dumps(kw, separators=(",", ":")))
        raw = raw.strip()
        if not raw:
            raise GameError(f"empty reply to {op} (mod not loaded?)")
        try:
            reply = json.loads(raw)
        except json.JSONDecodeError:
            raise GameError(f"non-JSON reply to {op}: {raw[:300]}")
        if not reply.get("ok"):
            raise GameError(reply.get("error", "unknown error"))
        data = reply.get("data")
        return {} if data == [] else data
