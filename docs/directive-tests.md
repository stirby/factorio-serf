# Directive tests: one player, given jobs like a person would

Since 2026-10-19 the main benchmark is a single agent (the serf) handed **directives**: the kind of "agh, I gotta
fix that next" job a player delegates in chat, with constraints. A run says each objective in chat as a pretend
player ("ops"), waits until the game confirms it (checks met in 2 consecutive one-minute samples) or its time runs
out, then says the next. Science progression is tested the same way, as a sequence of provided objectives.

Run one: `.venv/bin/python tests/bench.py --scenario experiments/scenarios/<name>.json --variant sonnet --instance 7`
(`--dry --selftest` checks the scenario's setup and that its checks read "met" when success is faked; no model).
Biters are always off. Results: `experiments/runs/<run>/result.json` (`objectives`: met, seconds, check values).

## Scenarios

| Name | Stage | The order | Checks |
|---|---|---|---|
| d1-iron-outpost | S3 | "add the iron patch I'm standing on [gps] to our system: electric drills, ore by belt to the train stop [gps], end by the track; load the wagon if you can. Power is at the stop. Belts, not bots." Setup lays a rail line, a stop, a parked train and power. | >= 8 drills on that patch; >= 40 ore on belts by the stop or in the wagon |
| d1b-iron-outpost-hard | S3 | Same, but "no power out there yet, and we're out of electric drills" (setup empties the drills from chests; no power at the stop). | same |
| d2-science-steps | S3 (2 idle labs, no science automated) | 1 research going; 2 red automated >= 15/min; 3 green automated >= 10/min; 4 six labs working | capacity of non-starved assemblers + labs working/consuming |
| d3-circuits | S6 (circuits short, copper furnaces backed up) | "build a circuit block that adds at least 120 a minute, fed from our iron and copper, output where needed" | capacity +120/min and circuits used +100/min, held 4 samples |
| f1-feldspar-iron | the user's world (copy, live mods) | "our iron is the bottleneck: a lot of machines are starved of iron plates. Go fix it." | iron plates made +900/min and used +600/min, held 3 samples |

Checks measure capacity and delivery, not "made per minute": a block that makes more than its consumers use backs
up and its made-rate drops, which is not a failure (learned in d2 run 1).

## Results

| Run | Variant | Outcome | Time | Cost (notional) | Notes |
|---|---|---|---|---|---|
| d1 #1 (2026-10-19 00:16) | Sonnet | met | 4 min | $0.39 | Took drills/belts/poles from base chests, walked 300 tiles, 10 drills, 51-tile belt, 4 inserters into the wagon, verified ore flowing. Then unprompted: queued research, fixed a jammed iron belt corner 100 tiles away. |
| d2 #1 (00:23) | Sonnet | 3 of 4 met | 48 min | $3.32 | research on 4 min; red: built a 12-furnace copper column + belt, 29/min made by min 14, but the old check (labs must use 5/min; 2 labs use ~4) was impossible: scenario bug, fixed; green 22 min; six labs 2 min. Time split: 45% model thinking (310 calls, ~4 s each), 35% acting, 17% waiting (7% with nothing running). No `calc` use. |
| d1b #1 (01:13) | Sonnet | met | 5 min | $0.31 | No drills in stock: queued 10 to craft in the background while walking; ran a 54-pole line ~300 tiles from the base grid with one `build line`; drills, belt, 4 wagon inserters, fueled the locomotive. The outpost directive is solved at this size; harder tests matter more. |
| d3 #1 (01:20) | Sonnet | met (old check) | 6 min | $0.61 | Stamped a 180/min circuit block in 2 min, but fed it from hand-filled chests into an output chest, and said so itself. The capacity-only check passed a stopgap: now delivery (used +100/min) must hold 4 samples, and the prompt says every constraint in the order counts. Then it found the real blue-science blocker (unpaired underground starving the plastic plant) and fixed it unprompted. |
| f1 #1 (01:28) | Sonnet | met (old check) | 16 min | $0.81 | Diagnosed in 3 min: 44 drills at the north outpost backed up while a 24-furnace smelter sat idle. Traced the 900-tile ore trunk and fixed two dead-end belts left by the old crew; iron made 7,300 -> 9,000/min. But the smelter had no output belts (plates on the ground), starved machines didn't drop; it found this and was building the output when the made-only check stopped the run. Check now requires use +600/min. Also asked absent crew agents for help once (prompt fixed). |
| f1 #2 (01:47) | Sonnet | not met (strict check), score 0.17 | 50 min | $4.75 | Same diagnosis in 1 min. Cut off by a river, it fetched stone and landfilled across; fixed 2 ore-belt breaks, built the smelter's missing output belts, put undergrounds under 2 belt crossings: iron made 7,350 -> ~9,000/min by min 17. Then it fell back to ~7,660: ore is the cap (~7,100 ore/min mined) and it said so ("more ore mining is the next lever"), but did not build drills. It drifted to downstream symptoms instead: copper-ore junk on iron lanes (drain chests), circuits 1,445 -> 2,144/min, blue-science pipes, purple science 21 -> 63/min. Useful work, wrong order. Asked permission before removing the user's belts. Time: 39% thinking, 24% waiting with nothing running, 23% acting. |
