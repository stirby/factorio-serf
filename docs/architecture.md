# Crew architecture

Current design (2026-10-18, after removing the order/actor layer; history in the build log below):

| Part | Runs on | Does |
|---|---|---|
| Foreman (`crew/foreman.py`) | Opus, no character | Decides what the crew works on. Hands out board tasks to workers with precise specs and an optional `done_when` check; answers `ask_foreman` questions without blocking; takes crew-wide chat; owns roadmap and research queue. Woken by humans, questions, finished/failed tasks, idle workers, research done, and a 5-min review. |
| Workers (`crew/agent.py`) | Sonnet (any backend), each a character | Own an outcome end to end. Keep working while they own an open task; sleep only when they own nothing. Act with `act` (place, mine, craft, connect, ...) and `build` (one call: stamp/paste/ghosts/line, done by the controller). |
| Controller (`crew/controller.py`) | plain code behind `build` | Lays a plan as ghosts, fetches items from chests and machine outputs, crafts, mines raw resources, clears blockers, builds, refuels; splits long belt routes. Resumable. |
| Board (`crew/board.py`) | shared JSON | Tasks with owner, notes, optional `done_when` (+ zone). The game evaluates checks every 20 s; a task is done only when its check holds 2 min (`orchestrator._task_checks`). |
| Mod (`mod/claude-crew`) | Lua | Characters, job queue under player rules, observations, late-game queries (`diagnose`, `copy`/`paste`, planners, `network`), checks (`scripts/orders.lua`). A failed action no longer cancels the rest of a batch unless it says `stop_on_fail=true`. |

Principles that came out of the log analysis (docs/log-analysis/README.md): the brain plans precisely and the hands
execute; checks measure delivery, not a moment; nothing tells a worker to go idle while it owns work; tools show
what agents otherwise guess (inserter pickup/drop, belt lanes, fluids, which pack starved labs miss).

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

