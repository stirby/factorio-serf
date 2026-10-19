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

Nothing is running. All test servers start with biters off (`crew/peace.py`). Repo: github.com/stirby/claude-crew
(private; making it public needs a history rewrite to drop 23 committed saves, and a license).

## The thesis (the user's)

Factorio is a lot like programming, so a good player = **best coding-agent practices + best Factorio
practices**. The mapping to work from:

| Coding agent practice | Factorio equivalent | What we have / need |
|---|---|---|
| Plan before editing; write a spec | Design the block (ratios, footprint, inputs/outputs) before placing | foreman prompt had this; the single player needs it in its own prompt |
| Tests that prove it works | `done_when` checks held for 2 min (rate used, working) | have it (board tasks) |
| Read before you write | `inspect`/`look` before placing; know belt lanes and inserter pickup/drop | partly: inspect shows dir/pickup/drop; fluids missing (C5) |
| Debugger / profiler | `diagnose` (machine status, starved inputs), production stats | have it; fluids missing |
| Libraries, don't rewrite | Blueprints: copy/paste known-good builds, `build stamp` | have it (`crew/blueprints`, copy/paste) |
| Small steps, commit often | One block at a time, verified, then the next | prompt |
| To-do list | Own board tasks | have it |
| Project memory (CLAUDE.md) | Notes: where things are, what's planned | have it (notes tool) |
| Background jobs while you think | Character keeps working while the model thinks: queue the next jobs first | NOT done: characters idle 55-65% |
| Fix root causes | Fix the bottleneck the stats show, not the symptom | foreman prompt rule; move to player |
| Know the critical path | Labs fed and growing; research is the score | opening routine (D1) |

Factorio practices to encode: labs are the critical path (feed them, grow the lab row, take free trigger techs
first, cheap techs first); build to ratios; power ahead of demand; a mall for building materials; main bus or
clear lanes; expand mining before it runs dry.

## Next (in order, paced: at most one heavy run at a time, mind the subscription limits)

1. The user tries the real thing: launch option, `serf`, `/serf add` in single player, then with a friend.
2. Open-source prep (if the user agrees): drop saves from history, license, mod name.
3. Directive tests under the new "one order, report, ask" behavior: d3 circuits (strict check), d2 science steps,
   f1 iron (it must now hold the iron order instead of drifting to other fixes).
4. Tools and consistency over speed (the user's call on thinking time; notes in docs/architecture.md).
5. Smaller tool fixes: fluids in diagnose/checks (C5), `place` clears trees (C3), pole routing (C2).

## For the morning conversation

What worked, what failed, and the evidence are in `docs/crew-design.md` (results table) and
`docs/log-analysis/README.md`. Overnight work is logged in the build log at the bottom of `docs/architecture.md`.
