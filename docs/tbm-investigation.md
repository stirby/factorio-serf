# Transport Belt Madness as a serf benchmark: investigation (2026-10-20)

**Summary.** TBM ships with the headless 2.0.77 install, but as a single-player **campaign**, not a scenario. Its script crashes on a headless server at tick 238 because it assumes `game.players[1]`. Its island maps load fine on their own, though, and they convert to ordinary saves. I tested one end to end on a throwaway instance. **Recommendation: option (c).** Turn the three TBM island maps into bench stage saves, and rebuild TBM's chest and inserter layout and its solved check in `setup_lua` / `score`. That's about a day of work and gives five authentic belt-routing levels.

## 1. Where TBM is and how it works

The `base/scenarios` folder doesn't have it. Built-in content in `server/factorio/data/` (only `base` has any; `core`, `space-age`, `quality` and `elevated-rails` have no scenarios, campaigns or tutorials):

| kind | path (under `data/base/`) | entries |
|---|---|---|
| scenarios | `scenarios/` | freeplay, pvp, rocket-rush, sandbox, supply, team-production, wave-defense |
| campaigns | `campaigns/` | **transport-belt-madness**, tight-spot, tutorial (NPE "New Hope", 5 levels) |
| tutorials | `tutorials/` | entity-transfers, stack-transfers, trains-stations, trains-basic-signals, trains-advanced-signals |
| menu sims | `menu-simulations/` | menu background sims (not playable) |

TBM files:
```
data/base/campaigns/transport-belt-madness/
  description.json            {"starting-level":"level-01","multiplayer-compatible":false}
  lualib/transportbeltmadness.lua   (395 lines: all logic, uses core story.lua + mod-gui)
  level-01/{control.lua,blueprint.zip}   -> game levels 1-2 ("Warm up", "First serious head scratching")
  level-02/{control.lua,blueprint.zip}   -> game levels 3-4
  level-03/{control.lua,blueprint.zip}   -> game level 5
```

### How levels are defined
- **The terrain** is a binary map: `blueprint.zip` → `blueprint/blueprint.dat`, the old scenario map format, map version 1.2.0-93. It holds a grass island in water and a few small side islands with solar panels and small poles. Those power the inserters. It contains no chests and no puzzle entities.
- **The puzzle** is a plain Lua table in each `control.lua`. Each chest pair is `{item, input=row, output=row}`. Positions come from a formula: input chest at `x = -ceil(level_width/2)`, `y = -ceil(#chests/2) + input`, with an inserter one tile east; output chest at `x = +ceil(level_width/2)` with a fast inserter one tile west. Level 5 gives explicit positions instead: `input_position = {{x,y}, dir}`.
  ```lua
  { item="iron-plate", input=1, output=5 },   -- level 1: row 1 on the left goes to row 5 on the right
  ```
- **Setup** (`transport_belt_madness_create_chests`): a steel chest holds 20 of the item, and an `inserter` (inactive) feeds the island. A `red-chest` is pre-seeded with 1 of its own item, with a `fast-inserter` (inactive) feeding it. Every one of these entities is set `operable=false, minable=false`, and the inserters are also `rotatable=false`.

### What the player can do
- They play in **god controller with `cheat_mode = true`**: there is no character body, and items are effectively unlimited. Each allowed item is inserted once and put on the quickbar.
- `force.disable_all_prototypes()`, then only `level.recipes` are enabled: belt and underground for levels 1–3; fast variants added in level 4; express variants plus `long-handed-inserter` in level 5. Research is disabled, and recipe groups, the minimap and pollution are turned off.
- `check_built_items`: on `on_built_entity`, anything not on the allowed list is destroyed. Allowed entities are set `active=false` while building. On `on_player_cursor_stack_changed`, a disallowed item in the cursor is cleared.
- The GUI is `mod_gui` buttons: **Start** and **Clear level** while building, **Back to building** while running. Level descriptions appear through `game.show_message_dialog`.

### How a level is solved and advanced
- **Start** saves the built entities (`export_entities`), switches the player to the ghost controller, and activates all the inserters.
- The check runs on every `on_tick`, through `story_update`, in `transport_belt_madness_check_level`:
  ```lua
  local item_count = chest.get_item_count()
  if item_count ~= chest.get_item_count(item.item) then   -- any foreign item => fail
    return {"failed", prototypes.item[item.item].localised_name}
  end
  if item_count ~= 21 then allfull = false end          -- 1 seed + all 20 delivered
  ...
  if allfull then return "finished" end
  ```
  A wrong item jumps to "level-failed", where **Back** restores the saved build with `map_load()`. When every output chest reaches 21, the level is cleared (`map_clear`), `current_level += 1`, and the next level's chests are created. After the last level in a `control.lua`, the campaign moves on to the next `level-0N` map.

### Exact layouts

Extracted in-game by running TBM's placement formula on each map (instance 60, see §4). Coordinates are entity centres. Inputs face east into the island, and outputs are fed from the west, except in level 5.

Maps: the level-01 and level-02 maps both have land bbox x −22..22, y −5..7; the level-03 map has x −16..14, y −16..12.

The level-01 map (game levels 1–2) has a central island of 17×13 tiles, x −8..8 by y −5..7. Inputs sit at x −6.5 with inserters dropping at x −4.3. Outputs sit at x 7.5, picked up from x 5.5. That leaves **11 buildable columns** (x −5..5).

| level | pairs (input y → output y) | items allowed |
|---|---|---|
| 1 | iron −0.5→3.5, copper 0.5→2.5, steel 2.5→−0.5, copper-ore 3.5→0.5 | belt, underground |
| 2 | iron −2.5→2.5, copper −1.5→3.5, steel −0.5→−2.5, cu-ore 0.5→4.5, fe-ore 2.5→−1.5, coal 3.5→5.5, wood 4.5→0.5, gear 5.5→−0.5 | belt, underground |

The level-02 map (game levels 3–4) is a wider island with two water inlets in the middle. Inputs sit at x −14.5 and outputs at x 15.5, which leaves ~25 columns.

| level | pairs | items allowed |
|---|---|---|
| 3 | 6 pairs (iron, copper, gear, steel, coal, circuit), rows −1.5..4.5, all permuted | belt, underground |
| 4 | 8 pairs, rows −2.5..5.5, all permuted | + fast belt/underground |

The level-03 map (game level 5) is a 31×29 island with water channels and solar blocks in the middle. It has **14 pairs** on all four edges, including uranium-ore going right→left and several going top↔bottom. Allowed items add express belts and long-handed inserters.

ASCII of the level-01 map with level 1 placed (I/i = input chest/inserter, o/O = output inserter/chest, P = pole, S = solar, ~ = water):
```
    .....~.....~~~.................~~~.....~.....      y=-5
    .SSS.~.SSS.~~~.................~~~.SSS.~.SSS.
    .SSS.~.SSS.~~~.................~~~.SSS.~.SSS.
    .SSS.~.SSS.~~~P...............P~~~.SSS.~.SSS.
    ....P~....P~~~.Ii...........oO.~~~.P...~.P...      y=-1
    ~~~~~~~~~~~~~~.Ii...........oO.~~~~~~~~~~~~~~      y=0
    .....~.....~~~.................~~~.....~.....
    PSSS.~PSSS.~~~.Ii...........oO.~~~.SSSP~.SSSP
    .SSS.~.SSS.~~~.Ii...........oO.~~~.SSS.~.SSS.
    .SSS.~.SSS.~~~P...............P~~~.SSS.~.SSS.
    .....~.....~~~.................~~~.....~.....
    ~~~~~~~~~~~~~~.................~~~~~~~~~~~~~~
    ~~~~~~~~~~~~~~.................~~~~~~~~~~~~~~      y=7
x=-22                                          x=22
```
Full dumps for all five levels: rerun `/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/tbm/probe2.py` (it reads a level's `control.lua` and prints the pairs and the ASCII).

## 2. Headless server and our mod

- **`--start-server-load-scenario` can't name a campaign level.** It looks in `<write-data>/scenarios/` or `<mod>/scenarios/`. Copying a level into a scenario directory works: put `control.lua`, `blueprint.zip`, `transportbeltmadness.lua`, `locale/` and `description.json` in `<instance>/scenarios/tbm-l1/`, then run `--start-server-load-scenario tbm-l1`.
- **The real TBM script crashes headless.** The map loads, the server reaches InGame at tick 238, and then:
  ```
  Error while running event level::on_tick (ID 0)
  __level__/transportbeltmadness.lua:310: attempt to index field '?' (a nil value)
      (story action 1: game.players[1].disable_recipe_groups())
  MultiplayerManager failed ... Quitting: multiplayer error.
  ```
  The whole script is hard-wired to `game.players[1]`: the god controller, cheat_mode, quickbar, GUI buttons, message dialogs, `clear_items_inside`. `description.json` also says `"multiplayer-compatible": false`.
- **Mod coexistence is fine in principle.** The scenario and each mod run in separate Lua states with separate `storage`, so event handlers don't collide. TBM registers no remote interfaces or commands.
  - Our mod's builds use `surface.create_entity{..., raise_built=true}` (`jobs.lua:513`). That raises `script_raised_built`, not `on_built_entity`, so TBM's build filter would neither destroy nor deactivate serf-built belts.
  - The serf **is not a LuaPlayer**. It's a `character` entity made with `surface.create_entity` (`agents.lua:66`). So it can never be TBM's "player 1", press the Start button, or receive TBM's GUI and dialogs.
  - TBM's `map_clear()` destroys every entity except characters, poles and solar panels. A level change would therefore wipe whatever the serf had built, which is fine, and it would leave the serf's character alive.
- **Only the map is needed, and it works headless with our mod.** I tested this on instance 60:
  - A scenario with TBM's `blueprint.zip` and an empty `control.lua` loads headless. `crew ping` answers (mod 0.3.1).
  - `spawn` puts the serf at (0,0), which is on the island.
  - `factorio --scenario2map tbm-map` writes a normal save (`saves/tbm-map.zip`, 240 KB) that `--start-server` loads like any stage.

## 3. Options

**(a) Run the actual TBM scenario headless, with the serf joining.** Not viable without forking TBM's script. It crashes with zero players. Even with a human or bot client connected as player 1, the serf can't click Start, and the solver would be player 1 in god mode with infinite items, not the serf. Making it work means replacing the `game.players[1]` calls, the GUI start/back flow and cheat_mode with something serf-aware. At that point it is option (c) with extra baggage. It also wouldn't fit the bench, which starts from `--start-server <save>` and runs `setup_lua` through our mod's `eval`. Effort: high. Value: none beyond (c).

**(b) Extract the layouts and rebuild them as `setup_lua` on a normal stage map** (like `t-belt-ore`: `find()` an open area, then `put()` chests and inserters, with an `electric-energy-interface` for power). This is easy and reuses the t-logistics generator. The cost is that TBM's confinement goes away. Its difficulty comes from the island: 11 columns between inputs and outputs in levels 1–2, water inlets in 3–4, water channels and edge-to-edge pairs in level 5. On open grass the serf can just route around everything. Confinement could be faked with `set_tiles` water or `out-of-map` around the area, but then you are rebuilding the island by hand.

**(c) Recommended: TBM island maps as stage saves, with TBM logic in `setup_lua` / `score`.** It's the authentic terrain and power islands, with our own legit-rules harness.
1. Make three stages. For each TBM `level-0N/blueprint.zip`: create a scenario dir with that zip and `-- empty` as `control.lua`, then run `factorio -c <cfg> --scenario2map <name>` with the serf mod enabled. Save the results as `server/factorio/saves/stage-tbm-{a,b,c}.zip`; a = levels 1–2, b = levels 3–4, c = level 5. There are no biters on these maps.
2. Write `experiments/scenarios/t-tbm-1.json` … `t-tbm-5.json`, or one JSON per map with two `objectives`. `setup_lua` does the following:
   - Places the pairs from the tables in §1.
   - Sets `always_day = true`, because the inserters run on solar.
   - Fills each input with 20 items.
   - Leaves the inserters `active=false` and sets everything `minable/operable=false`.
   - Teleports the serf onto the island.
   - **Gives the serf real items**: e.g. 150 belts and 30 undergrounds per level, plus fast/express for levels 4–5. TBM's cheat_mode is replaced by a finite stock, and how many it uses is a metric.
3. **Start trigger.** TBM's Start button becomes the first sample where every input inserter has a belt at its drop position and every output inserter has a belt at its pickup position (`surface.find_entities_filtered{position=..., type={"transport-belt","underground-belt"}}`). At that point the score Lua activates the inserters. The alternative is to activate them when the serf says it's done; the objective flow already nudges on idle.
4. **Done check** (score Lua, ported from TBM):
   - `pairs_full`: the number of output chests with `get_item_count() == 21` and no foreign item. The target is the number of pairs.
   - `no_wrong_items`: 1 or 0.
   - Optional: `belts_used`, with no target, as a metric.

   On a wrong item, TBM's fail-and-back can be mirrored. Deactivate the inserters, clear the belt contents and the wrong output, refill the inputs, and `chat` the TBM text "Level failed. Wrong item in the X chest". That gives the serf a retry inside the objective's minutes.
5. A **static pre-check** is cheap to add, and it would also catch solutions that work by luck. Walk `belt_neighbours.outputs` (for undergrounds, `neighbours`) from each input's drop belt and confirm it reaches the matching output's pickup belt without merging into another route.

Effort for (c): about half a day for the stage saves plus the level-1 scenario and its selftest, then about an hour per extra level. Most of the time goes into the selftest solutions, which need a valid routing written by hand.

I prototyped (c) on instance 60 with the level-01 map and level-1 chests and a deliberately wrong straight belt on row −0.5. The solar-powered inserters ran. After 20 s the steel output chest held 13 `iron-plate`, the input had 2 left, and the other inputs still had 18. Flow and wrong-item detection behave as expected. Rebuilding is what TBM itself does internally, so nothing about the puzzle is lost.

**What the serf's legit rules imply**
- TBM's player has no body and unlimited items. The serf walks and has a reach of about 10 tiles. That's fine: every island is under 32 tiles across, and it can walk on land.
- The serf can't cross water. On the level-03 map the channels split off parts of the island, so check that the serf can reach all of it, or let it place undergrounds from shore. Belts can be placed under a standing character.
- The serf's mod has an A* belt router with underground hops (`scripts/route.lua`). Routing pairs one at a time can block later pairs. That ordering and planning problem is exactly what TBM tests, and it makes a good discriminator.
- The serf can't get items any other way: recipes still work on a stage map, but there is no ore here. So setup must hand over the items. Giving them is fine per the bench conventions.

## 4. Dry run (done)
Throwaway **instance 60** (`server/instances/60`, game port 34260, RCON 27160). Instances 40–48 already had leftovers, so I didn't use them, and I didn't touch 20. It ran with the bench mod set (base, space-age, quality, elevated-rails, factorio-serf) and `bench-mod-settings.dat`.

| run | result |
|---|---|
| real TBM level-01 via `--start-server-load-scenario tbm-l1` | loads the map, then crashes at tick 238 (above) |
| TBM map + empty control.lua, three maps | loads; serf spawns; layouts extracted |
| `--scenario2map tbm-map` → `--start-server saves/tbm-map.zip` + setup/belt/check via `crew eval` | works (flow + wrong-item seen) |

All servers are stopped. The directory is left in place (1.2 MB: scenario copies, logs and `saves/tbm-map.zip`). It is safe to delete. Probe scripts: `/tmp/claude-1000/-home-stephen-ops/dca040bd-512a-4ed8-b7ff-9ffd9741ccde/scratchpad/tbm/probe{,2,3}.py`.

## 5. Other built-in content that could make serf tests
All of these were untested headless unless noted. The campaigns, like TBM, assume `game.players[1]`, so mine them for maps and logic the same way.
- **tight-spot** (campaign, 5 levels, `campaigns/tight-spot/`). Buy land and machines from a market with 10 000 coins, then sell gear wheels, circuits, solar panels, rockets or blue science within 10–15 min. Tests compact layout under space and money limits; the serf would need market buy/sell support.
- **supply** (scenario, `script/supply/control.lua`). About 20 timed levels; each asks for items in red chests (15 stone, then 30 iron, … up to science, belts and inserters). Tests steady production against a clock, a natural staged bench. It's `multiplayer-compatible` and its levels are a clean Lua table.
- **team-production** (scenario, `script/team-production/`). Short "produce N of X from given input" challenges (`config.lua`: e.g. 400 accumulators from batteries, 1000 copper cable) on prepared maps in `map_sets.lua`. Tests small self-contained factories, and many challenge templates are ready-made.
- **wave-defense** (scenario). Defend a silo against biter waves while earning points. Tests military and turret supply; biters are off in our bench, so it's a separate track.
- **rocket-rush** (scenario). All tech unlocked with a chosen starting kit; launch ASAP. A long-horizon throughput test, too big for micro-benchmarks.
- **tutorial / New Hope** (campaign, 5 levels: Crash, Mining outpost, Power Plant, Science and automation, Abandoned rail base). Each is a scripted early-game step with clear goals, e.g. power-plant setup and repairing a rail base. These are good "legit early game" checkpoints; levels 4–5 are MP-capable.
- **entity-transfers / stack-transfers** (tutorials). Inventory and entity transfer drills: fuel a furnace, move stacks. Trivial for the serf's API but a quick sanity test of insert/take.
- **trains-stations / basic-signals / advanced-signals** (tutorials). Prepared rail layouts with station-naming and signalling goals. A train-skill test if the serf ever gets rail and signal tools.
