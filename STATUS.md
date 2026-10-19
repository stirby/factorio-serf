# Status (2026-10-18, end of day)

**Focus: one good player.** One model-driven character in the world, as good as it can be. The crew (Opus foreman
+ Sonnet workers) is paused and documented in `docs/crew-design.md`. Design: `docs/architecture.md`.

Identity: the agent is an **engineer** (Factorio's word for its player), a peer: panel "claude · engineer with otterplex". Panel + overhead show live state; idle only on usage limits.

Nothing is running. All test servers start with biters off (`crew/peace.py`). Repo: github.com/stirby/claude-crew
(private).

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

1. Scoring: science packs consumed per minute and per dollar (A3 in `docs/log-analysis/README.md`). Without it we
   can't tell if a change helped.
2. Single-player prompt: fold the foreman's planning rules, the opening routine and the table above into the
   player's own prompt (`crew/prompt.py`).
3. Busy while thinking: queue the next jobs before each model turn; measure character idle %.
4. Baseline race on the s3 research-rush stage: one Sonnet player vs one Opus player (~45 min each).
5. Per-person agents ("a fella just joins"): per-orchestrator queues in the mod's `poll` (today one global queue,
   so two orchestrators steal each other's chat), then a one-command join.
6. Smaller tool fixes: fluids in diagnose/checks (C5), `place` clears trees (C3), pole routing (C2).

## For the morning conversation

What worked, what failed, and the evidence are in `docs/crew-design.md` (results table) and
`docs/log-analysis/README.md`. Overnight work is logged in the build log at the bottom of `docs/architecture.md`.
