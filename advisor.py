#!/usr/bin/env python3
"""Claude Advisor bridge: reads Factorio script-output, calls Claude, replies via RCON.

env:
  ANTHROPIC_API_KEY        required
  FACTORIO_RCON_PASSWORD   required
  FACTORIO_RCON_HOST       default 127.0.0.1
  FACTORIO_RCON_PORT       default 27015
  FACTORIO_SCRIPT_OUTPUT   default ~/.factorio/script-output
  CLAUDE_MODEL             default claude-sonnet-5-5
  ADVISE_EVERY_SEC         default 300 (passive check interval, real seconds)
"""
import json
import os
import socket
import struct
import sys
import textwrap
import time
from collections import deque
from pathlib import Path

import anthropic

OUT = Path(os.environ.get("FACTORIO_SCRIPT_OUTPUT", "~/.factorio/script-output")).expanduser() / "claude-advisor"
STATE, CHAT = OUT / "state.json", OUT / "chat.jsonl"
HOST = os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1")
PORT = int(os.environ.get("FACTORIO_RCON_PORT", "27015"))
PASSWORD = os.environ.get("FACTORIO_RCON_PASSWORD", "")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
ADVISE_EVERY = int(os.environ.get("ADVISE_EVERY_SEC", "300"))
RATE_WINDOW_TICKS = 60 * 60 * 5  # rates averaged over ~5 game minutes

SYSTEM = """You are a passive advisor inside a Factorio 2.0 game, speaking in in-game chat.
You get periodic snapshots: research, entity counts per surface, item production/consumption
rates (items/min over a few minutes), net deficits, alerts, player inventories, enemy evolution.

Rules:
- Terse. Chat lines, plain text, no markdown. Max 2 sentences when unsolicited.
- Passive mode: speak only if something is actionable and non-obvious (a growing deficit,
  stalled or empty research queue, alerts piling up, evolution outpacing defenses, a clear
  next bottleneck). Otherwise reply exactly: PASS
- Don't repeat earlier advice unless the problem got worse. Don't narrate the state back.
- When asked directly, answer concisely from the data; say plainly when the data can't answer it."""


class Rcon:
    def __init__(self, host, port, password):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.id = 0
        self._send(3, password)
        while True:
            rid, typ, _ = self._recv()
            if typ == 2:  # SERVERDATA_AUTH_RESPONSE
                break
        if rid == -1:
            raise RuntimeError("RCON auth failed")

    def _send(self, typ, body):
        self.id += 1
        data = struct.pack("<ii", self.id, typ) + body.encode() + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(data)) + data)

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON closed")
            buf += chunk
        return buf

    def _recv(self):
        (size,) = struct.unpack("<i", self._read(4))
        data = self._read(size)
        rid, typ = struct.unpack("<ii", data[:8])
        return rid, typ, data[8:-2].decode(errors="replace")

    def cmd(self, command):
        self._send(2, command)
        return self._recv()[2]


def totals(state, key):
    out = {}
    for s in state.get("surfaces", {}).values():
        for item, n in (s.get(key) or {}).items():
            out[item] = out.get(item, 0) + n
    return out


def rates(history):
    cur = history[-1]
    base = next((h for h in history if h["tick"] <= cur["tick"] - RATE_WINDOW_TICKS), history[0])
    minutes = (cur["tick"] - base["tick"]) / 3600
    if minutes <= 0:
        return None
    res = {}
    for key in ("produced", "consumed"):
        a, b = totals(base, key), totals(cur, key)
        res[key] = {k: round((b[k] - a.get(k, 0)) / minutes, 1) for k in b if b[k] - a.get(k, 0) > 0}
    res["window_min"] = round(minutes, 1)
    return res


def summarize(history):
    cur = history[-1]
    t = cur["tick"] // 60
    out = {
        "game_time": f"{t // 3600}h{(t % 3600) // 60:02d}m",
        "research": cur.get("research"),
        "research_queue": cur.get("research_queue"),
        "surfaces": {n: {"entities": s.get("entities"), "evolution": round(s["evolution"], 3) if "evolution" in s else None}
                     for n, s in cur.get("surfaces", {}).items()},
        "players": [],
    }
    for p in cur.get("players", []):
        inv = p.get("inventory") or []
        if isinstance(inv, list):
            inv = {i["name"]: i["count"] for i in inv}
        top = dict(sorted(inv.items(), key=lambda kv: -kv[1])[:15])
        out["players"].append({k: p.get(k) for k in ("name", "surface", "position", "alerts")} | {"inventory_top": top})
    r = rates(history)
    if r:
        top = lambda d: dict(sorted(d.items(), key=lambda kv: -kv[1])[:25])
        out["rates_per_min"] = {"window_min": r["window_min"], "produced": top(r["produced"]), "consumed": top(r["consumed"])}
        out["deficits_per_min"] = {k: round(c - r["produced"].get(k, 0), 1) for k, c in r["consumed"].items()
                                   if c > 1 and c > r["produced"].get(k, 0) * 1.05}
    return out


def ask(client, history, chat_log, said, question=None):
    parts = ["STATE:\n" + json.dumps(summarize(history), separators=(",", ":"))]
    if chat_log:
        parts.append("RECENT CHAT:\n" + "\n".join(f"{c['player']}: {c['message']}" for c in chat_log))
    if said:
        parts.append("YOUR RECENT MESSAGES:\n" + "\n".join(said))
    parts.append(f"QUESTION from {question['player']}: {question['message']}" if question
                 else "PASSIVE CHECK: anything worth saying? Otherwise PASS.")
    resp = client.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                                  messages=[{"role": "user", "content": "\n\n".join(parts)}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def say(rcon, text):
    for para in text.splitlines():
        for line in textwrap.wrap(para.strip(), 300):
            rcon.cmd("/claude_say " + line)


def main():
    if not PASSWORD:
        sys.exit("set FACTORIO_RCON_PASSWORD")
    client = anthropic.Anthropic()
    rcon = None
    history = deque(maxlen=20)
    chat_log, said = deque(maxlen=20), deque(maxlen=8)
    state_mtime = 0.0
    chat_off = CHAT.stat().st_size if CHAT.exists() else 0  # ignore chat from before startup
    last_passive, last_passive_tick = time.time(), -1
    print(f"watching {OUT}, rcon {HOST}:{PORT}, model {MODEL}")

    while True:
        try:
            if rcon is None:
                rcon = Rcon(HOST, PORT, PASSWORD)
                print("rcon connected")

            if STATE.exists() and STATE.stat().st_mtime != state_mtime:
                state_mtime = STATE.stat().st_mtime
                try:
                    st = json.loads(STATE.read_text())
                    if history and st["tick"] < history[-1]["tick"]:
                        history.clear()  # different save loaded
                    if not history or st["tick"] != history[-1]["tick"]:
                        history.append(st)
                except (json.JSONDecodeError, KeyError):
                    state_mtime = 0.0  # partial write; retry next loop

            if CHAT.exists():
                size = CHAT.stat().st_size
                if size < chat_off:
                    chat_off = 0
                if size > chat_off:
                    with CHAT.open("rb") as f:
                        f.seek(chat_off)
                        data = f.read()
                    end = data.rfind(b"\n") + 1
                    chat_off += end
                    for raw in data[:end].splitlines():
                        try:
                            c = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if c.get("addressed") and history:
                            reply = ask(client, history, list(chat_log), list(said), question=c)
                            if reply and reply != "PASS":
                                say(rcon, reply)
                                said.append(reply)
                        chat_log.append(c)

            if (history and time.time() - last_passive >= ADVISE_EVERY
                    and history[-1]["tick"] != last_passive_tick and len(history) >= 2):
                last_passive, last_passive_tick = time.time(), history[-1]["tick"]
                reply = ask(client, history, list(chat_log), list(said))
                if reply and reply.strip() != "PASS":
                    say(rcon, reply)
                    said.append(reply)

            time.sleep(1)
        except (ConnectionError, socket.error) as e:
            print(f"rcon: {e}; retrying in 5s")
            rcon = None
            time.sleep(5)
        except anthropic.APIError as e:
            print(f"claude api: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
