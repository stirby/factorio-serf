# Architecture

## Direction (2026-10-18): one good player

All testing and iteration now centers on **one model-driven player in the world**. The multi-agent crew (an Opus
foreman directing Sonnet workers) is paused; its design, results and how to re-enable it are in
[crew-design.md](crew-design.md). Why: in a 3-hour live run the crew spent most of its time thinking, the characters
were idle 55-65% of game time, and a brain without hands added cost, not output. The way to scale is more
individually capable players, not a hierarchy.

The product: **a player brings their own Claude login and their own agent just joins the game**. Since mod 0.2.0
(2026-10-19): start your game with `--enable-lua-udp 27200`, run `serf`, type `/serf add`. Several people means
several independent serfs, each on its owner's login.

### How players' apps reach the game (mod 0.2.0)

- **Transports** (`crew/game.py` picks one): RCON (`crew/rcon.py`, a server operator, trusted) or localhost UDP
  (`crew/udp.py` + `mod/.../scripts/link.lua`, a player's own app). Mods can't make web requests, so the model
  always runs outside the game. Factorio 2.0's `helpers.recv_udp`/`send_udp` read a packet on the machine that
  got it and turn it into an input action: every peer runs the request identically (no desync), and
  `send_udp(port, reply, player_index)` sends the reply only from that player's machine. Works in single player
  and from a multiplayer client, with no access to the server needed.
- **Framing:** `CC1 <id> <part> <parts>\n<chunk>`, chunks of 60 KB cut on UTF-8 boundaries. Replies go out at
  most 3 packets per tick from a per-machine queue: a burst bigger than the app's socket buffer (208 KB on stock
  Linux) is dropped. The app asks for an 8 MB buffer.
- **Clients and the feed:** every orchestrator is a client (RCON: `client` in the request, default `rcon`; UDP:
  `p<player_index>`). Chat and events go into one feed (`storage.feed`, 600 entries); each client reads from its
  own cursor, so nobody steals anyone's messages. An agent records its client and owner; its job results and
  events go only to its client. Polling is the heartbeat (offline after 20 s).
- **Guards for UDP clients** (`guard` in control.lua): no `eval`/`chat`/`brand`/`as_player`; drive only your own
  agents; names can't be taken over; `claude-crew-serfs-per-player` cap (2); no starter kit in multiplayer;
  `claude-crew-player-serfs` off disables it all. The app on the server's own machine (player 0) may spawn for a
  named player.
- **`/serf add`** pushes an `add` event to that player's app (or to an operator's `crew up --host-serfs`), which
  picks a name (`serf`, then `serf-<player>`), spawns next to the player and starts the brain. `@serf` in chat
  means the speaker's own serf (`Orchestrator._alias`). Serfs persist in the save; the app re-attaches its own
  on restart. State per world: `~/.local/state/serf/world-<seed>`.
- **Known Factorio issue:** a headless 2.0.77 server started with `--enable-lua-udp` crashes when a packet arrives
  ("Trying to add invalid input action to the closure"), so UDP is only for players' own games, and
  `tests/test_udp.py` tests the in-game side through the RCON-only `as_player` op (same dispatch and guards). The
  real client path needs a game client to test.

| Part | Runs on | Does |
|---|---|---|
| Player (`crew/agent.py`) | one model (Sonnet or Opus), one character | Plays: decides, acts, checks its own work. Owns a to-do list on the board. |
| Tools (`crew/tools.py`, `crew/late_tools.py`) | plain code | `act` (place, mine, craft, connect, configure, ...), `build` (stamp/paste/ghosts/line in one call, done by the controller), `diagnose`, copy/paste, planners, `network`, `research`. |
| Controller (`crew/controller.py`) | plain code behind `build` | Lays a plan as ghosts, fetches items, crafts, mines raw resources, clears blockers, builds, refuels. |
| Checks (`orchestrator._task_checks`, mod `scripts/orders.lua`) | the game | A board task with `done_when` closes only when its check holds 2 min. |
| Mod (`mod/claude-crew`) | Lua | Characters under player rules, job queue, observations, late-game queries, checks. JSON API over RCON (`/crew`) or localhost UDP; `/serf` for players. |
| Apps (`crew/cli.py`) | Python | `serf`: a player's own app (UDP, join mode). `crew up`: a server operator's (RCON; `--host-serfs`). |

What people see (one player at a time, so make it watchable): the panel (top left, `/crew-panel`) is titled
"serf · with otterplex" (`[identity]` in crew.toml; the user's name for it: short to type, "@serf fix our
iron". The prompt treats it as a fellow engineer and teammate) and shows, per agent: model, a live state line, its task, and its
latest thought in quotes. The same state floats over the character's head. States: `thinking... 12s` (a model
turn is running; with the job if the character is also moving), the current job (`walking to 60,10`, `mining`,
`building`), `paused: hourly spend cap`, `retrying: <error>`, `offline` (no orchestrator poll for 20 s), and
`idle: out of Claude usage`, and `waiting for orders from <owner>` after it finished an order and asked what's
next (the user's call, 2026-10-19: "it should ask for guidance upon finishing a task"). It works one order at a
time, stays on it until its check holds, notes side problems instead of chasing them, then reports what it did,
the numbers, and 2-3 things worth doing next.
Pushed by `Agent.show()` (crew/agent.py) through the mod's `status` API; drawn by `scripts/panel.lua`.

Test rules: **biters are always off in tests** (`crew/peace.py`, applied by `scripts/instance.py` and
`scripts/server.sh` on every start); tests run on copies of saves, never the original.

### Thinking time (notes, 2026-10-19)

The model thinks for 39-45% of wall time (median ~2.5-4 s per call, longer after map reads), and in the iron run the
character also sat with nothing queued 24% of the time. The user's read: this is a general limit of agents today;
short of a faster model there's no way to fake zero downtime, so focus on tools and consistency. What helps
anyway, roughly in order of payoff:
- Bigger tools: one call doing more (the `build` controller did 50-87 entities per call with no model calls).
  Each new macro (find_space, calc, build line) removed several think-act rounds.
- Fewer map reads: they're the slowest turns (median 6.7 s after a map). find_space answers "where does this fit".
- Queue the next jobs before thinking (the job queue already runs while the model thinks; the prompt asks for it,
  but it isn't enforced or measured per turn yet).
- A fast model for routine steps (walk, fetch, refuel) and the strong one for design: not tried in solo mode.
- Show the thinking (done): the panel's live thought makes the wait feel like a teammate thinking, not lag.

What to improve next (from `docs/log-analysis/README.md`): score by science packs consumed per minute and per
dollar (A3); keep the character busy while the model thinks (queue the next jobs before thinking); visibility of
belts, inserters and fluids (C1, C5); `place` clears trees itself (C3); pole routing (C2).

## Build log

- 2026-10-18: architecture agreed; order graph + scheduler (`crew/orders.py`), controller (`crew/controller.py`),
  actor (`crew/actor.py`), coordinator order tools (`crew/foreman.py`), mod queries `zone`/`sources`/`check`
  (`mod/claude-crew/scripts/orders.lua`). Controller tested without a model on stage S7: pasted a 34-piece smelting
  column on open ground, fetched belts/inserters from chests, mined stone, crafted furnaces, built it all in 108 s,
  check passed. Actor + scheduler + coordinator not yet tested end to end.
- 2026-10-18: PAUSED for a prior-art review before building further. Several existing projects use the same
  "model picks the task, mod executes" split (AI Player v3, AI Companion / factorio-ai-companion, factorioctl,
  Factorio AI Coworker, FLE). Decide reuse vs build before continuing; see docs/prior-art.md.
- 2026-10-18: prior-art review done (docs/prior-art.md, notes in research_notes/). Verdict: keep the orchestrator
  and order design; port the game layer module by module from MIT projects (factorio-mcp in llm-play-factorio,
  factorio-codex); no fork or rebase.
- 2026-10-18 18:52: first live run (S7 robots save, Opus coordinator + 3 Haiku actors, "@all our iron is the
  bottleneck, go fix it"). Coordinator diagnosed "iron isn't short, it's stuck" in 60 s ($0.30) and wrote 3 orders;
  an actor closed a one-tile belt gap (iron 771 -> 1094/min); the coordinator then found copper was the real limit
  and re-targeted. 14 min: 12 orders, 4 wasted on impossible checks (zone vs base counts). Cost: coordinator $3.18,
  three actors ~$0.12 total. Fixes: checks take "scope": "base"; a check that can never pass (asks for more than
  exist) blocks immediately with the reason instead of retrying.
- 2026-10-18 19:50: order system benchmark (round 17, Opus coordinator + Haiku actors, s3-research-rush): 0 new
  techs in ~45 min, ~$25 per run; stopped. Failure modes: one-moment checks passed while problems recurred, the
  coordinator fixed symptoms (repeated refuel orders), malformed orders (connect with cargo as item), long belt
  routes failing. Judged a regression vs the player crews (+6 techs in 35-59 min).
- 2026-10-18 19:50: SIMPLIFIED. Removed actor.py, orders.py and the scheduler. Kept: the controller, as one worker
  tool `build` (stamp/paste/ghosts/line in one call: tested, a 51-piece red science block in 38 s); board tasks with
  optional game-evaluated done_when that must hold 2 min; foreman hands out outcomes with checks. Known issue: long
  `line` routes still fail near dense base areas even after automatic splitting. Not benchmarked yet.
- 2026-10-18 20:31-23:45: live run on a copy of the user's world (feldspar, 42 h, biters on): Opus foreman + 4
  Sonnet workers. 3 new techs, 5 checked tasks, 5 deaths to biters in 30 min, characters idle 55-65%. Stopped as
  unproductive.
- 2026-10-18: PIVOT to one good player; crew design archived in crew-design.md. Biters always off in tests.
