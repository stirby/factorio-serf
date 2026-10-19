# Architecture

## Direction (2026-10-18): one good player

All testing and iteration now centers on **one model-driven player in the world**. The multi-agent crew (an Opus
foreman directing Sonnet workers) is paused; its design, results and how to re-enable it are in
[crew-design.md](crew-design.md). Why: in a 3-hour live run the crew spent most of its time thinking, the characters
were idle 55-65% of game time, and a brain without hands added cost, not output. The way to scale is more
individually capable players, not a hierarchy.

The product this points at: **a player brings their own Claude login and their own agent just joins the game**.
Each person runs `crew up` with one agent on their own subscription (or API key); the agent spawns as a character,
plays alongside them, and takes orders from them in chat. Several people means several independent agents.
Not possible yet: the mod's `poll` drains one global chat/event queue (`control.lua` API.poll), so a second
orchestrator on the same server steals the first one's messages. Needed: per-orchestrator queues (register a
client id, keep a queue per id, route each agent's results to its owner), then a one-command join.

| Part | Runs on | Does |
|---|---|---|
| Player (`crew/agent.py`) | one model (Sonnet or Opus), one character | Plays: decides, acts, checks its own work. Owns a to-do list on the board. |
| Tools (`crew/tools.py`, `crew/late_tools.py`) | plain code | `act` (place, mine, craft, connect, configure, ...), `build` (stamp/paste/ghosts/line in one call, done by the controller), `diagnose`, copy/paste, planners, `network`, `research`. |
| Controller (`crew/controller.py`) | plain code behind `build` | Lays a plan as ghosts, fetches items, crafts, mines raw resources, clears blockers, builds, refuels. |
| Checks (`orchestrator._task_checks`, mod `scripts/orders.lua`) | the game | A board task with `done_when` closes only when its check holds 2 min. |
| Mod (`mod/claude-crew`) | Lua | Characters under player rules, job queue, observations, late-game queries, checks. RCON JSON API `/crew`. |

What people see (one player at a time, so make it watchable): the panel (top left, `/crew-panel`) is titled
"claude · engineer with otterplex" (`[identity]` in crew.toml; the agent is a fellow engineer, Factorio's own
word for its player, never an object) and shows, per agent: model, a live state line, its task, and its
latest thought in quotes. The same state floats over the character's head. States: `thinking... 12s` (a model
turn is running; with the job if the character is also moving), the current job (`walking to 60,10`, `mining`,
`building`), `paused: hourly spend cap`, `retrying: <error>`, `offline` (no orchestrator poll for 20 s), and
`idle: out of Claude usage`, the only idle. A solo agent never sleeps: with no task it picks the next goal itself.
Pushed by `Agent.show()` (crew/agent.py) through the mod's `status` API; drawn by `scripts/panel.lua`.

Test rules: **biters are always off in tests** (`crew/peace.py`, applied by `scripts/instance.py` and
`scripts/server.sh` on every start); tests run on copies of saves, never the original.

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
