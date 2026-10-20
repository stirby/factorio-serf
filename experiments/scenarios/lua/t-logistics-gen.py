"""Builds the t-* logistics micro scenarios (experiments/scenarios/t-*.json) from the Lua next to this file.

    python3 experiments/scenarios/lua/t-logistics-gen.py

Each setup_lua = t-logistics-common.lua + t-<name>-setup.lua. Checks and selftests are short and live here.
Micro scenarios: one task a player would hand over in chat, 8-12 minutes, checks on real outcomes (things moving,
machines working), so hand-feeding from chests doesn't pass.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
COMMON = (HERE / "t-logistics-common.lua").read_text()
STAGE = "stage-s3-steel-oil-ready"

# Count entities of `name` in storage.<key>.<box> whose status is working.
WORKING = ("local b=storage.{key} local n=0 for _,e in pairs(s.find_entities_filtered{{area=b.{box}, name='{name}'}}) do "
           "if e.status==defines.entity_status.working then n=n+1 end end return n")
# Machines of `name` in storage.<key>.<box> that finished something since the previous sample (status flickers
# when an input runs a little short; this doesn't).
PRODUCING = ("local b=storage.{key} b.seen=b.seen or {{}} local n=0 for _,e in pairs(s.find_entities_filtered{{"
             "area=b.{box}, name='{name}'}}) do local p=e.products_finished if p>(b.seen[e.unit_number] or 0) then "
             "n=n+1 end b.seen[e.unit_number]=p end return n")
# Items of `item` lying on belts in storage.<key>.<box>.
ON_BELTS = ("local b=storage.{key} local n=0 for _,e in pairs(s.find_entities_filtered{{area=b.{box}, "
            "type={{'transport-belt','underground-belt','splitter'}}}}) do for i=1,e.get_max_transport_line_index() do "
            "n=n+e.get_transport_line(i).get_item_count('{item}') end end return n")
# Shared selftest prelude: put() at X+x, Y+y, clearing trees first.
ST = ("local b=storage.{key} local X,Y=b.X,b.Y local D=defines.direction "
      "local function put(n,x,y,d,t) for _,e in pairs(s.find_entities_filtered{{position={{X+x,Y+y}},radius=0.9,"
      "type={{'tree','simple-entity'}}}}) do e.destroy() end local e=s.create_entity{{name=n,position={{X+x,Y+y}},"
      "direction=d,force='player',type=t}} if not e then error('selftest: no '..n..' at '..x..','..y) end return e end\n")

SCENARIOS = [
    {
        "name": "t-belt-ore",
        "note": "Micro (logistics): belt ore from a drill stub to a furnace row 26 tiles away, past a crossing belt "
                "(undergrounds or a detour) and trees. Passes only if ore actually flows: the drills keep working "
                "(their stub would otherwise back up), the furnaces smelt, and ore sits on the furnaces' input belt.",
        "minutes": 10,
        "objective": {
            "name": "ore-to-furnaces",
            "goal": "@{agent} the drills at [gps={drills}] are backing up. Belt their ore to the furnaces at "
                    "[gps={furnaces}] (their input belt is already there).",
            "answer": "Any route is fine, just don't cut the belt that runs north-south between them, it's in use.",
            "hold_samples": 2,
            "score": [
                {"name": "drills_working", "lua": WORKING.format(key="bench_belt_ore", box="drills",
                                                                  name="electric-mining-drill"), "target": 3},
                {"name": "furnaces_smelting", "lua": PRODUCING.format(key="bench_belt_ore", box="furnaces",
                                                                       name="stone-furnace"), "target": 4},
                {"name": "ore_on_input_belt", "lua": ON_BELTS.format(key="bench_belt_ore", box="furnaces",
                                                                      item="iron-ore"), "target": 1},
                {"name": "crossing_belt_intact",
                 "lua": "local b=storage.bench_belt_ore local n=0 for _,e in pairs(s.find_entities_filtered{area="
                        "{{b.X+24,b.Y-9},{b.X+25,b.Y+19}}, name='transport-belt'}) do if e.direction==defines.direction.south "
                        "then n=n+1 end end return n", "target": 28},
            ],
            "selftest": ST.format(key="bench_belt_ore") +
            "local FX=b.FX for x=16,FX-3 do if x==23 then put('underground-belt',23.5,3.5,D.east,'input') "
            "elseif x==25 then put('underground-belt',25.5,3.5,D.east,'output') elseif x~=24 then "
            "put('transport-belt',x+0.5,3.5,D.east) end end "
            "put('transport-belt',FX-1.5,3.5,D.south) put('transport-belt',FX-1.5,4.5,D.south) "
            "put('transport-belt',FX-1.5,5.5,D.east) return 'belted'",
            "wait": 45,
        },
    },
    {
        "name": "t-power-line",
        "note": "Micro (logistics): run power 48 tiles from a grid pole to an unpowered block of 4 gear assemblers, "
                "over a 4-wide stream (poles reach over water). Passes when all 4 assemblers work on the grid's own "
                "network (not some new generator).",
        "minutes": 8,
        "objective": {
            "name": "power-the-block",
            "goal": "@{agent} the gear assemblers at [gps={block}] have no power. Hook them up to the grid, the "
                    "nearest pole is at [gps={pole}].",
            "answer": "Small poles are fine. Use the grid pole I pointed at.",
            "hold_samples": 2,
            "score": [
                {"name": "assemblers_producing", "lua": PRODUCING.format(key="bench_power", box="block",
                                                                          name="assembling-machine-1"), "target": 4},
                {"name": "on_grid",
                 "lua": "local b=storage.bench_power local id=b.pole.valid and b.pole.electric_network_id local n=0 "
                        "for _,e in pairs(s.find_entities_filtered{area=b.block, name='assembling-machine-1'}) do "
                        "if id and e.electric_network_id==id then n=n+1 end end return n", "target": 4},
            ],
            "selftest": ST.format(key="bench_power") +
            "for _,x in pairs{8.5,15.5,18.5,25.5,32.5,39.5,46.5} do put('small-electric-pole',x,-1.5) end "
            "return b.pole.electric_network_id",
            "wait": 5,
        },
    },
    {
        "name": "t-coal-boilers",
        "note": "Micro (logistics): the boiler keeps running out of coal; belt coal to it from burner drills 28 tiles "
                "away (stub already backed up) and feed it with an inserter. Hand-feeding alone fails: an inserter "
                "must feed the boiler from a belt that has coal on it near the boiler.",
        "minutes": 10,
        "objective": {
            "name": "coal-to-boiler",
            "goal": "@{agent} the boiler at [gps={boiler}] keeps running out of coal. Belt coal to it from the "
                    "drills at [gps={coal}] so it stays fed.",
            "answer": "Belt it, don't hand-feed it. Any route is fine.",
            "hold_samples": 2,
            "score": [
                {"name": "boiler_burning",
                 "lua": "local b=storage.bench_coal.boiler return b.valid and b.status==defines.entity_status.working "
                        "and 1 or 0", "target": 1},
                {"name": "belt_fed",
                 "lua": "local b=storage.bench_coal.boiler local n=0 if not b.valid then return 0 end "
                        "for _,i in pairs(s.find_entities_filtered{position=b.position, radius=4, type='inserter'}) do "
                        "local p=i.pickup_target if i.drop_target==b and p and (p.type=='transport-belt' or "
                        "p.type=='underground-belt' or p.type=='splitter') then n=n+1 end end return n", "target": 1},
                {"name": "coal_on_belt_at_boiler",
                 "lua": "local b=storage.bench_coal.boiler local n=0 if not b.valid then return 0 end "
                        "for _,e in pairs(s.find_entities_filtered{position=b.position, radius=4, type={'transport-belt',"
                        "'underground-belt','splitter'}}) do for i=1,e.get_max_transport_line_index() do "
                        "n=n+e.get_transport_line(i).get_item_count('coal') end end return n", "target": 1},
                {"name": "coal_drills_working", "lua": WORKING.format(key="bench_coal", box="drills",
                                                                       name="burner-mining-drill")},
            ],
            "selftest": ST.format(key="bench_coal") +
            "for x=8,32 do put('transport-belt',x+0.5,2.5,D.east) end put('transport-belt',33.5,2.5,D.south) "
            "put('transport-belt',33.5,3.5,D.south) for x=33,36 do put('transport-belt',x+0.5,4.5,D.east) end "
            "local i=put('burner-inserter',36.5,3.5,D.south) i.insert{name='coal',count=2} return 'belted'",
            "wait": 40,
        },
    },
    {
        "name": "t-cross-bus",
        "note": "Micro (logistics): get copper from a stub on one side of a 4-lane main bus to a chest's inserter on "
                "the other side, without cutting the bus (undergrounds span it exactly, or go around its end). Passes "
                "on copper arriving in the chest at >= 20/min through its inserter from a belt, with all 180 bus "
                "belts still in place facing south.",
        "minutes": 10,
        "objective": {
            "name": "copper-across-bus",
            "goal": "@{agent} I need copper plates in the chest at [gps={chest}]. They come out on the belt at "
                    "[gps={stub}]; get them across, and don't break the main bus in between.",
            "answer": "The inserter next to the chest is already set up, just bring the belt to it.",
            "hold_samples": 2,
            "score": [
                {"name": "copper_per_min",
                 "lua": "local d=storage.bench_bus.dest return d.valid and d.get_item_count('copper-plate') or 0",
                 "rate": True, "target": 20},
                {"name": "inserter_takes_from_belt",
                 "lua": "local i=storage.bench_bus.ins local p=i.valid and i.pickup_target return p and (p.type=="
                        "'transport-belt' or p.type=='underground-belt' or p.type=='splitter') and 1 or 0", "target": 1},
                {"name": "bus_intact",
                 "lua": "local b=storage.bench_bus local n=0 for _,e in pairs(s.find_entities_filtered{area=b.bus, "
                        "name='transport-belt'}) do if e.direction==defines.direction.south then n=n+1 end end return n",
                 "target": 180},
            ],
            "selftest": ST.format(key="bench_bus") +
            "for x=8,18 do put('transport-belt',x+0.5,2.5,D.east) end put('underground-belt',19.5,2.5,D.east,'input') "
            "put('underground-belt',24.5,2.5,D.east,'output') for x=25,39 do put('transport-belt',x+0.5,2.5,D.east) end "
            "return 'belted'",
            "wait": 60,
        },
    },
    {
        "name": "t-smelter-column",
        "note": "Micro (logistics/build): 8 stone furnaces fed from a mixed ore+coal belt, plates out on a belt to a "
                "chest's inserter 12 tiles south. Passes on 8 furnaces each fed by an inserter from a belt and making "
                "plates, and >= 60 plates/min arriving in the chest through its inserter from a belt.",
        "minutes": 12,
        "objective": {
            "name": "eight-furnaces",
            "goal": "@{agent} build 8 stone furnaces off the ore belt at [gps={ore}] (it carries iron ore and coal), "
                    "and send the plates on a belt to the chest at [gps={chest}].",
            "answer": "Anywhere south of the ore belt is fine. The chest's inserter is already there, end the plate "
                      "belt next to it.",
            "hold_samples": 2,
            "score": [
                {"name": "furnaces_smelting", "lua": PRODUCING.format(key="bench_smelt", box="area",
                                                                       name="stone-furnace"), "target": 8},
                {"name": "furnaces_belt_fed",
                 "lua": "local b=storage.bench_smelt local n=0 for _,fu in pairs(s.find_entities_filtered{area=b.area, "
                        "name='stone-furnace'}) do for _,i in pairs(s.find_entities_filtered{position=fu.position, "
                        "radius=2.5, type='inserter'}) do local p=i.pickup_target if i.drop_target==fu and p and "
                        "(p.type=='transport-belt' or p.type=='underground-belt' or p.type=='splitter') then n=n+1 break "
                        "end end end return n", "target": 8},
                {"name": "plates_per_min",
                 "lua": "local d=storage.bench_smelt.dest return d.valid and d.get_item_count('iron-plate') or 0",
                 "rate": True, "target": 60},
                {"name": "chest_inserter_takes_from_belt",
                 "lua": "local i=storage.bench_smelt.ins local p=i.valid and i.pickup_target return p and (p.type=="
                        "'transport-belt' or p.type=='underground-belt' or p.type=='splitter') and 1 or 0", "target": 1},
            ],
            "selftest": ST.format(key="bench_smelt") +
            "for k=0,7 do local x=10.5+2*k put('inserter',x,1.5,D.north) put('stone-furnace',x+0.5,3) "
            "put('inserter',x,4.5,D.north) end "
            "for _,x in pairs{11.5,15.5,19.5,23.5,25.5} do put('small-electric-pole',x,1.5) put('small-electric-pole',x,4.5) end "
            "for x=10,27 do put('transport-belt',x+0.5,5.5,D.east) end "
            "for y=5,12 do put('transport-belt',28.5,y+0.5,D.south) end return 'built'",
            "wait": 75,
        },
    },
]


def build(sc: dict) -> dict:
    ob = sc["objective"]
    setup = COMMON + "\n" + (HERE / f"{sc['name']}-setup.lua").read_text()
    return {
        "name": sc["name"], "stage": STAGE, "minutes": sc["minutes"], "agents": 1, "kind": "directive",
        "group": "logistics", "note": sc["note"], "setup_lua": setup,
        "objectives": [{"name": ob["name"], "minutes": sc["minutes"], "hold_samples": ob.get("hold_samples", 2),
                        "goal": ob["goal"], "answer": ob["answer"], "score": ob["score"],
                        "selftest_lua": ob["selftest"], "selftest_wait": ob.get("wait", 5)}],
        "score": [],
    }


if __name__ == "__main__":
    import sys
    only = set(sys.argv[1:])
    for sc in SCENARIOS:
        if only and sc["name"] not in only:
            continue
        (OUT / f"{sc['name']}.json").write_text(json.dumps(build(sc), indent=1) + "\n")
        print("wrote", sc["name"])
