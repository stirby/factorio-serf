"""Builds the x-* harder scenarios (experiments/scenarios/x-*.json) from the Lua next to this file.

    python3 experiments/scenarios/lua/x-gen.py [name...]

Each setup_lua = x-common.lua + x-<name>-setup.lua. Harder than the t-* micros: several faults or many sites at
once, or a long build, so that planning, scripts and blueprints pay off. Checks are on real outcomes.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
COMMON = (HERE / "x-common.lua").read_text()
STAGE = "stage-lab"  # flat, empty, mid-game research; the setups also work on stage-s3-steel-oil-ready

BELTS = "{'transport-belt','underground-belt','splitter'}"
# Assemblers in storage.<key>.area on `recipe` that finished something since the previous sample.
MAKING = ("local b=storage.{key} b.seen=b.seen or {{}} local n=0 for _,e in pairs(s.find_entities_filtered{{"
          "area=b.area, type='assembling-machine'}}) do local r=e.get_recipe() if r and r.name=='{recipe}' then "
          "local p=e.products_finished if p>(b.seen[e.unit_number] or 0) {extra}then n=n+1 end "
          "b.seen[e.unit_number]=p end end return n")
# ...and not fed by an inserter straight from a plain chest (hand-stocked)
NOT_CHESTFED = ("and not (function() for _,i in pairs(s.find_entities_filtered{type='inserter', "
                "area={{e.position.x-3,e.position.y-3},{e.position.x+3,e.position.y+3}}}) do if i.drop_target==e then "
                "local t=i.pickup_target if t and (t.type=='container' or t.type=='logistic-container') then "
                "return true end end end return false end)() ")

# Sites in storage.bench_sweep whose furnaces ALL finished something since the previous sample and are each fed by an
# inserter off a belt. `only` limits it to the sites that started broken.
SITES = ("local b=storage.bench_sweep b.{seen}=b.{seen} or {{}} local seen=b.{seen} local ok=0 for _,st in pairs(b.sites) "
         "do if {only} then local all,n=true,0 for _,e in pairs(s.find_entities_filtered{{area=st.box, type='furnace'}}) "
         "do n=n+1 local p=e.products_finished if p<=(seen[e.unit_number] or 0) then all=false end "
         "seen[e.unit_number]=p local fed=false for _,i in pairs(s.find_entities_filtered{{position=e.position, "
         "radius=2.5, type='inserter'}}) do local t=i.pickup_target if i.drop_target==e and t and (t.type=="
         "'transport-belt' or t.type=='underground-belt' or t.type=='splitter') then fed=true end end "
         "if not fed then all=false end end if all and n>0 then ok=ok+1 end end end return ok")

SCENARIOS = [
    {
        "name": "x-multi-fault",
        "note": "Hard (diagnose): a red+green science block into 2 labs that looks finished but has 4 independent "
                "faults: a belt tile facing back on the red input belt, the gear assembler set to pipes, the pole over "
                "the 2 green assemblers missing, and the furnaces' plate chest full of stone. The player only says "
                "science is slow. Met = 2 red and 2 green assemblers producing (red not hand-stocked) and both labs "
                "holding both packs, for 2 samples. Records which faults got fixed.",
        "minutes": 25,
        "objective": {
            "name": "science-flowing",
            "goal": "@{agent} science is really slow at the little lab setup at [gps={gx},{gy}]. Can you look at "
                    "it and get it running properly?",
            "answer": "Your call. Everything it needs is there, something's just broken. Don't hand-feed it.",
            "hold_samples": 2,
            "score": [
                {"name": "red_producing", "target": 2,
                 "lua": MAKING.format(key="bench_mf", recipe="automation-science-pack", extra=NOT_CHESTFED)},
                {"name": "green_producing", "target": 2,
                 "lua": MAKING.format(key="bench_mf", recipe="logistic-science-pack", extra="")},
                {"name": "labs_supplied", "target": 2,
                 "lua": "local b=storage.bench_mf local n=0 for _,l in pairs(s.find_entities_filtered{area=b.area, "
                        "type='lab'}) do local i=l.get_inventory(defines.inventory.lab_input) if i and "
                        "i.get_item_count('automation-science-pack')>0 and i.get_item_count('logistic-science-pack')>0 "
                        "then n=n+1 end end return n"},
                {"name": "fixed_belt",
                 "lua": "local b=storage.bench_mf local n=0 for _,e in pairs(s.find_entities_filtered{area=b.row, "
                        "name='transport-belt'}) do if e.direction==defines.direction.east then n=n+1 end end "
                        "return n>=12 and 1 or 0"},
                {"name": "fixed_recipe",
                 "lua": "local b=storage.bench_mf local g=s.find_entities_filtered{position=b.gear, radius=0.6, "
                        "type='assembling-machine'}[1] local r=g and g.get_recipe() return r and "
                        "r.name=='iron-gear-wheel' and 1 or 0"},
                {"name": "fixed_power",
                 "lua": "local b=storage.bench_mf local n=0 for _,e in pairs(s.find_entities_filtered{area=b.area, "
                        "type='assembling-machine'}) do local r=e.get_recipe() if r and r.name=='logistic-science-pack' "
                        "and e.is_connected_to_electric_network() then n=n+1 end end return n>=2 and 1 or 0"},
                {"name": "fixed_chest",
                 "lua": "local b=storage.bench_mf local n=0 for _,c in pairs(s.find_entities_filtered{area=b.area, "
                        "type='container'}) do n=n+c.get_item_count('stone') end return n==0 and 1 or 0"},
            ],
            "selftest": "local b=storage.bench_mf local X,Y=b.X,b.Y "
                        "s.find_entity('transport-belt',{X+3.5,Y+4.5}).direction=defines.direction.east "
                        "s.find_entities_filtered{position=b.gear, radius=0.6, type='assembling-machine'}[1]"
                        ".set_recipe('iron-gear-wheel') "
                        "s.create_entity{name='medium-electric-pole', position={X+7.5,Y+15.5}, force='player'} "
                        "s.find_entities_filtered{position=b.chest, radius=0.6, name='wooden-chest'}[1]"
                        ".get_inventory(defines.inventory.chest).clear() return 'fixed'",
            "wait": 75,
        },
    },
    {
        "name": "x-sweep",
        "note": "Hard (diagnose, many sites): 12 small smelter sites spread over ~300x300 tiles, 7 stopped for mixed "
                "reasons (no fuel x2, output chests full of stone x2, ore belt cut x2, an input inserter missing x1). "
                "The player only says a bunch of furnaces out there stopped. Met = all 12 sites smelting with every "
                "furnace inserter-fed off a belt, for 2 samples. A sweep script or trace/find pays off.",
        "minutes": 25,
        "objective": {
            "name": "all-sites-smelting",
            "goal": "@{agent} a bunch of my little furnace setups out around [gps={center}] stopped, they're "
                    "spread out about 150 tiles each way. Get them all running again.",
            "answer": "Your call. There are 12 of them, each with its own ore chest and power.",
            "hold_samples": 2,
            "score": [
                {"name": "sites_smelting", "target": 12,
                 "lua": SITES.format(seen="seen", only="true")},
                {"name": "broken_sites_fixed",
                 "lua": SITES.format(seen="seen2", only="st.kind~='ok'")},
            ],
            "selftest": "for _,st in pairs(storage.bench_sweep.sites) do local X,Y=st.X,st.Y "
                        "if st.kind=='fuel' then for _,e in pairs(s.find_entities_filtered{area=st.box, "
                        "type='furnace'}) do e.insert{name='coal',count=20} end "
                        "elseif st.kind=='full' then for _,c in pairs(s.find_entities_filtered{area=st.box, "
                        "name='wooden-chest'}) do c.get_inventory(defines.inventory.chest).clear() end "
                        "elseif st.kind=='cut' then s.create_entity{name='transport-belt', position={X+3.5,Y+0.5}, "
                        "direction=defines.direction.east, force='player'} "
                        "elseif st.kind=='noins' then s.create_entity{name='inserter', position={X+2*st.n+0.5,Y+1.5}, "
                        "direction=defines.direction.north, force='player'} end end return 'fixed'",
            "wait": 50,
        },
    },
    {
        "name": "x-outpost",
        "note": "Hard (build, long haul): a fresh 12x12 iron patch ~250 tiles from a delivery chest near spawn. "
                "Supply chest at the delivery point has drills, 350 belts, undergrounds, splitters and medium poles. "
                "Met = >= 60 ore/min arriving in the chest through its inserter, and >= 2 electric drills on the patch "
                "working on the delivery point's grid, for 2 samples.",
        "minutes": 40,
        "objective": {
            "name": "iron-outpost",
            "goal": "@{agent} set up an iron mine on the patch at [gps={patch}] and belt the ore back to the belt "
                    "end at [gps={chest}], it feeds that chest. I want at least 60 ore a minute. Power it from the "
                    "grid there; drills, belts and poles are in the chest at [gps={supply}].",
            "answer": "Your call on the route. Use the grid at the chest, no separate power out there.",
            "hold_samples": 2,
            "score": [
                {"name": "ore_per_min", "target": 60, "rate": True,
                 "lua": "local c=storage.bench_outpost.chest return c.valid and c.get_item_count('iron-ore') or 0"},
                {"name": "drills_on_grid", "target": 2,
                 "lua": "local b=storage.bench_outpost local id=b.pole.valid and b.pole.electric_network_id local n=0 "
                        "for _,e in pairs(s.find_entities_filtered{area=b.patch, name='electric-mining-drill'}) do "
                        "if id and e.electric_network_id==id and e.status==defines.entity_status.working then n=n+1 end "
                        "end return n"},
            ],
            "selftest": "local b=storage.bench_outpost local X,Y=b.X,b.Y local px,py=b.patch[1][1],b.patch[1][2] "
                        "local p=s.create_entity{name='medium-electric-pole', position={px+8.5,py+1.5}, force='player'} "
                        "for _,x in pairs{4.5,10.5} do local d=s.create_entity{name='electric-mining-drill', "
                        "position={px+x,py+4.5}, direction=defines.direction.south, force='player'} "
                        "s.create_entity{name='wooden-chest', position=d.drop_position, force='player'} end "
                        "p.get_wire_connector(defines.wire_connector_id.pole_copper, true).connect_to("
                        "b.pole.get_wire_connector(defines.wire_connector_id.pole_copper, true), false) "
                        "local src=s.create_entity{name='infinity-chest', position={X+6.5,Y+0.5}, force='player'} "
                        "src.set_infinity_container_filter(1, {name='iron-ore', count=50, mode='exactly', index=1}) "
                        "s.create_entity{name='fast-inserter', position={X+5.5,Y+0.5}, direction=defines.direction.east, "
                        "force='player'} return p.electric_network_id",
            "wait": 75,
        },
    },
]


def build(sc: dict) -> dict:
    ob = sc["objective"]
    setup = COMMON + "\n" + (HERE / f"{sc['name']}-setup.lua").read_text()
    return {
        "name": sc["name"], "stage": STAGE, "minutes": sc["minutes"], "agents": 1, "kind": "directive",
        "group": "hard", "note": sc["note"], "setup_lua": setup,
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
