# Building like a player

The serf can launch a rocket, but its bases don't run. Left alone for five minutes, both rocket worlds make no
science at all (scripts/audit_base.py, 22 October 2026):

| Unattended, 5 min | c1 (fresh map, outside player) | p2 (own project, midgame) |
| --- | --- | --- |
| Science per minute | 0 (13 labs waiting for packs) | 0 (8 labs waiting) |
| Machines working | 19% of 222 | 6% of 230 |
| Starved / blocked | 50% / 27% | 37% / 54% |
| Belt tiles per machine | 22 | 21 |
| Pipe tiles per machine | 5 | 11 |
| Chests filled by hand | 25 | 18 |
| Ground per machine | 222 tiles | 500 tiles |

The rockets went up because the serf kept hand-carrying the missing parts. Every check we had asked "is X being
made right now?", while the serf was there to keep it going; nothing asked whether the base runs without it.

## What good players do

They pick a rate first ("45 science a minute"), work the chain back to ore, and build every step for that rate
with room to grow. Plates go onto a main bus; production sits in rows off the bus; smelting and power are built
well past today's demand; scaling up means copying a block, not re-routing. Nothing is fed by hand once it's
automated.

## The plan

1. **Measure what matters.** The score is *unattended science per minute*: stop the serf, run the world, count
   the science the labs consume. Supporting numbers: machines working, chests filled by hand (target 0), belt
   tiles per machine, and whether a "double it" order succeeds. Every generation of a campaign ends with this
   audit.
2. **Throughput in code.** `jev/ratios.py` turns a target rate into machines, oil setup, raw ore, drills and
   belts. The planner and the project manager size every build with it, with headroom.
3. **Rate-based orders and checks.** An order says the rate, the place and the margin ("45 green circuits a
   minute, in the circuit row, room to double"); its check measures the block's sustained output rate.
4. **A base plan.** The manager commits to a layout at the start: smelting area, main bus and its lanes,
   production rows off the bus, reserved oil and rocket areas. Builds go into the plan's slots.
5. **No hand-feeding.** Restocks and hand refuels are for the bootstrap only; after that they count against
   the base, and the manager hears about every one.
6. **Long runs.** The current serf against the plan-first serf on the same fresh worlds, 20 to 30 hours each,
   scored by the audit.
