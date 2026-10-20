# Status (2026-10-19)

**Focus: one good player.** One model-driven character in the world, as good as it can be. The crew (Opus foreman
+ Sonnet workers) is paused and documented in `docs/crew-design.md`. Design: `docs/architecture.md`.

Identity: the agent is **serf** (the user's pick; `@serf ...` in chat), a fellow engineer. Panel + overhead show
live state; idle only on usage limits; "waiting for orders" after it finishes an order and asks what's next.

**New (mod 0.2.0): anyone can bring their own serf.** Start Factorio with `--enable-lua-udp 27200`, run `serf`
(own Claude login), type `/serf add`. Works in single player and as a multiplayer client; several players, several
serfs, each on its owner's login. Servers can host serfs over RCON (`crew up --host-serfs`). Tested: framing, routing,
guards and the add flow (`tests/test_udp.py`, an end-to-end add with a real Sonnet turn, smoke 56/56). **Not yet
tested: the real UDP path from a game client** (needs the user's game; a headless server crashes on Lua UDP).

All test servers start with biters off (`crew/peace.py`). Repo: github.com/stirby/factorio-serf (public, MIT;
release v0.2.0). Benchmark saves (`experiments/runs/*/final.zip`) are in Git LFS (pre-rewrite mirror at
~/dev/factorio-serf-backup-20261019.git). The user's Factorio client has the mod linked from this checkout
(`scripts/install-client-mod.sh`, 2026-10-19 18:33; their mod-list backup is in the session scratchpad).

**Mod 0.3.1 (unreleased):** design library + **Teach serf** (toolbar button, ctrl+shift+T, `/serf learn [name]`):
hold a blueprint or a whole book (inventory or Game blueprints; My blueprints in single player only) and it goes
into the serf's library. Tools: `place` clears trees/rocks itself; pole lines hop by wire reach; belts and pipes go
under crossings and water; `diagnose` handles fluids. The user's direction (2026-10-19): one code path, focus on
the server side, single player once it's great.

## The thesis (the user's)

Factorio is a lot like programming, so a good player = **best coding-agent practices + best Factorio
practices**. The mapping to work from:

| Coding agent practice | Factorio equivalent | What we have / need |
|---|---|---|
| Plan before editing; write a spec | Design the block (ratios, footprint, inputs/outputs) before placing | foreman prompt had this; the single player needs it in its own prompt |
| Tests that prove it works | `done_when` checks held for 2 min (rate used, working) | have it (board tasks) |
| Read before you write | `inspect`/`look` before placing; know belt lanes and inserter pickup/drop | have it (inspect shows dir/pickup/drop, fluids) |
| Debugger / profiler | `diagnose` (machine status, starved inputs), production stats | have it, items and fluids |
| Libraries, don't rewrite | Blueprints: copy/paste known-good builds, `build stamp` | have it: built-ins + the serf's own library + designs players teach (d4: 0 hand placements) |
| Small steps, commit often | One block at a time, verified, then the next | prompt |
| To-do list | Own board tasks | have it |
| Project memory (CLAUDE.md) | Notes: where things are, what's planned | have it (notes tool) |
| Background jobs while you think | Character keeps working while the model thinks: queue the next jobs first | NOT done: characters idle 55-65% |
| Fix root causes | Fix the bottleneck the stats show, not the symptom | foreman prompt rule; move to player |
| Know the critical path | Labs fed and growing; research is the score | opening routine (D1) |

Factorio practices to encode: labs are the critical path (feed them, grow the lab row, take free trigger techs
first, cheap techs first); build to ratios; power ahead of demand; a mall for building materials; main bus or
clear lanes; expand mining before it runs dry.

## Directive tests (2026-10-19, details in docs/directive-tests.md)

Under "one order, report, ask" + "decide inside an order": d3b circuit mall met in 13 min ($1.04), f1 iron on the
user's world met in 31 min ($1.23; three earlier tries failed on drift, unanswered questions and a bad check).
Lessons: a delivery check needs a consumer that wants the delivery; the pretend player must answer questions.
d4-library (build two more of a taught design, powered) met in 2 min ($0.18): 2 stamps + 1 build, no hand placement.

## Next (in order, paced: at most one heavy run at a time, mind the subscription limits)

1. The user tries the real thing: launch option, `serf`, `/serf add` in single player, then with a friend.
2. Done: public, MIT, v0.2.0.
3. More directives. d2 science steps: #2 met on chest-fed stopgaps; #3 met with real belt-fed automation (35 min, $3.26).
4. Tools and consistency over speed (the user's call on thinking time; notes in docs/architecture.md).
5. Release mod 0.3.1 after the user's first real `/serf join`.

## Improvements (from playing; a list to work through, not all at once)

Lessons reviewed through: 2026-10-19 (see "Lessons loop" in CLAUDE.md; the only lesson so far is #2 below).

1. **Can't see where the serf is on the map** (user, 2026-10-19). A script character has no map marker the way a
   player does. Ideas: draw a marker with `rendering` in `render_mode = "chart"` that follows the character, or a
   chart tag updated every few seconds; a "find" button on the serf panel (`zoom_to_world` on its position);
   put `[gps=x,y]` in its status line. Mod change, so it ships with the next mod release.
2. **Belts and pipes it lays join other lines** (user, 2026-10-19): belts get fed by, or side-load into, belts
   carrying other items, and pipes join neighbouring fluid lines. Cause: the router (`route.find` in
   `scripts/route.lua`, called by the connect job in `jobs.lua`) only asks "can I place an entity on this tile?",
   never "what does this tile touch?". Fix: also count a tile as blocked when
   - (belts) a neighbouring belt, underground exit or splitter outputs into it, and
   - (pipes) a neighbouring entity has a pipe connection into it (`fluidbox.get_pipe_connections`),
   except at the line's own start and end, so it goes around or under (it already uses undergrounds when
   blocked). Add a regression test (connect next to a foreign belt and pipe) on a scratch instance. Mod change;
   do it in a worktree (instances link the mod from their own checkout), release with the next mod version.
3. Model/fast-mode chat changes don't persist across `serf` restarts (they reset to serf.toml). Write them back?
4. Fast mode on a subscription needs extra usage credits; the user's are exhausted, so `@serf fast on` only gets
   "usage credits exhausted" for now. Verify it really speeds up once credits exist (`usage.speed`).
5. Corpse looting is still TODO (mod change).
6. Name suggestions for "serf" (low priority, the user would like a few more).

## For the morning conversation

What worked, what failed, and the evidence are in `docs/crew-design.md` (results table) and
`docs/log-analysis/README.md`. Overnight work is logged in the build log at the bottom of `docs/architecture.md`.
