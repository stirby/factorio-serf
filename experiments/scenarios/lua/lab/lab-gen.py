"""Builds the x-* lab scenarios (experiments/scenarios/x-*.json) from the Lua next to this file.

    python3 experiments/scenarios/lua/lab/lab-gen.py [name...]

They run on the LAB stage (stage-lab.zip, built by make_stage_lab.py): a clean flat square, so every fixture sits
at a fixed origin and nothing from a base distracts the serf. Each setup_lua = lab-common.lua + x-<name>-setup.lua.
Inputs are full belts from infinity chests + loaders; building materials are in a supply chest the goal names, so
the serf fetches instead of guessing. Checks count only what machines fed by inserters from belts or other machines
made (a chest or the serf's hands feeding a machine disqualifies it). Selftests build a passing solution on their
own loader-fed belts beside the fixture: they prove the checks, not a layout.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1]
COMMON = (HERE / "lab-common.lua").read_text()
STAGE = "stage-lab"

# fedok(m): every inserter dropping into m picks from a belt or a machine (not a chest or a character), and there
# is at least one. Long-handed inserters stand 2 tiles off, hence the 4-tile search.
FEDOK = ("local function fedok(m) local n=0 for _,i in pairs(s.find_entities_filtered{type='inserter',force=f,"
         "area={{m.position.x-4,m.position.y-4},{m.position.x+4,m.position.y+4}}}) do if i.drop_target==m then "
         "local p=i.pickup_target if p then if p.type=='container' or p.type=='logistic-container' or "
         "p.type=='infinity-container' or p.type=='character' then return false end n=n+1 end end end return n>0 end ")
# Crafts finished by fed assemblers of RECIPE in storage.KEY.area (cumulative; with "rate": true, per minute).
MADE = (FEDOK + "local t=0 for _,m in pairs(s.find_entities_filtered{area=storage.KEY.area,force=f,"
        "type='assembling-machine'}) do local r=m.get_recipe() if r and r.name=='RECIPE' and fedok(m) then "
        "t=t+m.products_finished end end return t")
# ITEM held in chests in storage.KEY.area.
IN_CHEST = ("local t=0 for _,c in pairs(s.find_entities_filtered{area=storage.KEY.area,force=f,"
            "type={'container','logistic-container'}}) do t=t+c.get_item_count('ITEM') end return t")
# Scale ladder: how many of the sites SITES have a working column: 8+ belt-fed furnaces that finished a plate since
# the previous sample, and more iron plates in the site's chests than at the previous sample.
COLUMNS = (FEDOK + "local b=storage.bench_ladder local ok=0 for _,i in pairs({SITES}) do local st=b.sites[i] local n=0 "
           "for _,m in pairs(s.find_entities_filtered{area=st.box,force=f,type='furnace'}) do "
           "local p=m.products_finished if p>(b.seen[m.unit_number] or 0) and fedok(m) then n=n+1 end "
           "b.seen[m.unit_number]=p end local pl=0 for _,c in pairs(s.find_entities_filtered{area=st.box,force=f,"
           "type={'container','logistic-container'}}) do pl=pl+c.get_item_count('iron-plate') end "
           "local up=pl>(b.plates[i] or 0) b.plates[i]=pl if n>=8 and up then ok=ok+1 end end return ok")


def made(key, recipe):
    return MADE.replace("KEY", key).replace("RECIPE", recipe)


def in_chest(key, item):
    return IN_CHEST.replace("KEY", key).replace("ITEM", item)


# Selftest prelude: the fixture helpers (put, feed, ...) at the fixture's origin, plus power(x, y) an always-on
# source with a medium pole, asm(x, y, recipe), pole(x, y), and ins(x, y, side, long) an inserter that picks up from
# `side` ("north" picks from the north and drops south).
ST = (COMMON + "X, Y = storage.KEY.X, storage.KEY.Y\n"
      "local function power(x,y) local e=put('electric-energy-interface',x,y) e.power_production=166667 "
      "e.electric_buffer_size=10000000 put('medium-electric-pole',x+2.5,y+0.5) end "
      "local function asm(x,y,r) return put('assembling-machine-2',x,y,nil,{recipe=r}) end "
      "local function ins(x,y,d,long) return put(long and 'long-handed-inserter' or 'fast-inserter',x,y,D[d]) end "
      "local function pole(x,y) return put('medium-electric-pole',x,y) end\n")

RED_ST = (ST.replace("KEY", "bench_red") + """local R=30
feed({'iron-plate','plastic-bar'},0,R,'east',20) feed({'copper-plate'},0,R+6,'east',18)
power(-5,R+3) pole(1.5,R+5.5) pole(5.5,R+1.5) pole(9.5,R+5.5) pole(13.5,R+1.5) pole(17.5,R+5.5)
asm(3.5,R+3.5,'copper-cable') asm(7.5,R+3.5,'electronic-circuit') asm(11.5,R+3.5,'advanced-circuit')
asm(15.5,R+3.5,'copper-cable')
ins(3.5,R+5.5,'south') ins(5.5,R+3.5,'west') ins(7.5,R+1.5,'north') ins(9.5,R+3.5,'west')
ins(13.5,R+3.5,'east') ins(11.5,R+1.5,'north') ins(15.5,R+5.5,'south') ins(11.5,R+5.5,'north',true)
put('wooden-chest',11.5,R+7.5)
return 'red circuit chain built'""")

GREEN_ST = (ST.replace("KEY", "bench_green") + """local R=30
feed({'iron-plate'},0,R,'east',24) feed({'copper-plate'},0,R+6,'east',8)
power(-5,R+3) pole(1.5,R+5.5) pole(5.5,R+1.5) pole(9.5,R+5.5) pole(13.5,R+1.5) pole(17.5,R+5.5) pole(21.5,R+1.5)
pole(25.5,R+8.5) pole(25.5,R+12.5)
asm(3.5,R+3.5,'copper-cable') asm(7.5,R+3.5,'electronic-circuit') asm(11.5,R+3.5,'inserter')
asm(15.5,R+3.5,'iron-gear-wheel') asm(19.5,R+3.5,'transport-belt')
ins(3.5,R+5.5,'south') ins(5.5,R+3.5,'west') ins(7.5,R+1.5,'north') ins(9.5,R+3.5,'west')
ins(11.5,R+1.5,'north') ins(13.5,R+3.5,'east') ins(15.5,R+1.5,'north') ins(17.5,R+3.5,'west')
ins(19.5,R+1.5,'north') ins(11.5,R+5.5,'north',true)
-- belts side-load onto the north lane; the long inserter drops inserters on the far (south) lane
ins(19.5,R+5.5,'north') put('transport-belt',19.5,R+6.5,D.south)
for x=11,29 do put('transport-belt',x+0.5,R+7.5,D.east) end
asm(23.5,R+10.5,'logistic-science-pack') asm(27.5,R+10.5,'logistic-science-pack')
ins(23.5,R+8.5,'north') ins(27.5,R+8.5,'north') ins(23.5,R+12.5,'north') ins(27.5,R+12.5,'north')
put('wooden-chest',23.5,R+13.5) put('wooden-chest',27.5,R+13.5)
return 'green science chain built'""")


def ladder_st(sites):
    """A column at each site: furnaces east of the fixture's ore belt, an output belt down to the site's chest."""
    return (ST.replace("KEY", "bench_ladder") + "for _,i in pairs({" + ",".join(map(str, sites)) + "}) do "
            "local sx=(i-1)*16 put('electric-energy-interface',sx-2,8).power_production=166667 "
            "for _,py in pairs{3.5,9.5,15.5} do pole(sx+1.5,py) end pole(sx+3.5,19.5) "
            "for k=0,7 do local yc=1+2*k put('stone-furnace',sx+3,yc) ins(sx+1.5,yc-0.5,'west') "
            "ins(sx+4.5,yc-0.5,'west') end "
            "for y=0,19 do put('transport-belt',sx+5.5,y+0.5,D.south) end "
            "put('transport-belt',sx+5.5,20.5,D.west) put('transport-belt',sx+4.5,20.5,D.west) "
            "ins(sx+4.5,21.5,'north') end return 'columns built'")


def columns(sites):
    return COLUMNS.replace("SITES", ",".join(map(str, sites)))


SCENARIOS = [
    {
        "name": "x-red-circuits",
        "note": "Lab (production chain): full belts of iron plate, copper plate and plastic bar, a supply chest of "
                "building materials, a grid pole. Automate red (advanced) circuits into a chest, making the cables "
                "and green circuits there too. Checks: red circuits made per minute by fed assemblers (sustained), "
                "green circuits made by fed assemblers, red circuits in a chest.",
        "minutes": 45,
        "setup": "x-red-circuits-setup.lua",
        "objectives": [{
            "name": "red-circuits",
            "goal": "@{agent} I've got full belts of iron plates at [gps={fe}], copper plates at [gps={cu}] and "
                    "plastic at [gps={pl}]. Automate red circuits from them into a chest, at least 5 a minute. "
                    "Building materials are in the supply chest at [gps={supply}] and the grid pole is at "
                    "[gps={pole}].",
            "answer": "Your call on the layout. Make the cables and green circuits there too, from those belts, "
                      "not by hand.",
            "hold_samples": 2,
            "score": [
                {"name": "red_per_min", "lua": made("bench_red", "advanced-circuit"), "rate": True, "target": 5},
                {"name": "greens_made", "lua": made("bench_red", "electronic-circuit"), "target": 20},
                {"name": "red_in_chest", "lua": in_chest("bench_red", "advanced-circuit"), "target": 10},
            ],
            "selftest": RED_ST, "wait": 240,
        }],
    },
    {
        "name": "x-green-science",
        "note": "Lab (production chain): full belts of iron plate and copper plate, a supply chest of building "
                "materials, a grid pole. Automate logistic (green) science into a chest at 10/min, making the "
                "gears, cables, circuits, inserters and belts there too. Checks: packs per minute from fed "
                "assemblers (sustained), inserters and belts made by fed assemblers, packs in a chest.",
        "minutes": 35,
        "setup": "x-green-science-setup.lua",
        "objectives": [{
            "name": "green-science",
            "goal": "@{agent} there are full belts of iron plates at [gps={fe}] and copper plates at [gps={cu}]. "
                    "Automate green science from them into a chest, 10 a minute or more. Building materials are in "
                    "the supply chest at [gps={supply}], grid pole at [gps={pole}].",
            "answer": "Your call. Make everything in it (gears, circuits, inserters, belts) from those two belts.",
            "hold_samples": 2,
            "score": [
                {"name": "packs_per_min", "lua": made("bench_green", "logistic-science-pack"), "rate": True,
                 "target": 10},
                {"name": "inserters_made", "lua": made("bench_green", "inserter"), "target": 10},
                {"name": "belts_made", "lua": made("bench_green", "transport-belt"), "target": 5},
                {"name": "packs_in_chest", "lua": in_chest("bench_green", "logistic-science-pack"), "target": 20},
            ],
            "selftest": GREEN_ST, "wait": 300,
        }],
    },
    {
        "name": "x-scale-ladder",
        "note": "Lab (scale): seven sites in a row, each a full iron ore + coal belt running south and an empty "
                "chest at its foot. One 8-furnace smelter column, then two more like it, then four more. Doing each "
                "by hand is slow; saving the first as a blueprint (or a script) pays off. Checks per objective: "
                "sites whose 8+ belt-fed furnaces are all smelting and whose chest is filling.",
        "minutes": 65,
        "setup": "x-scale-ladder-setup.lua",
        "objectives": [
            {
                "name": "one-column", "minutes": 20,
                "goal": "@{agent} make me a smelter column: 8 stone furnaces off the ore belt at [gps={s1}] (iron "
                        "ore and coal on it), plates on a belt into the chest at [gps={c1}]. Materials are in the "
                        "supply chest at [gps={supply}], grid pole at [gps={pole}].",
                "answer": "Any layout, as long as all 8 smelt off the belt and the plates end up in that chest.",
                "hold_samples": 2,
                "score": [{"name": "columns_working", "lua": columns([1]), "target": 1}],
                "selftest": ladder_st([1]), "wait": 90,
            },
            {
                "name": "two-more", "minutes": 20,
                "goal": "@{agent} nice. Two more just like it: ore belts at [gps={s2}] and [gps={s3}], chests at "
                        "[gps={c2}] and [gps={c3}].",
                "answer": "Same as the first one.",
                "hold_samples": 2,
                "score": [{"name": "columns_working", "lua": columns([2, 3]), "target": 2}],
                "selftest": ladder_st([2, 3]), "wait": 90,
            },
            {
                "name": "four-more", "minutes": 25,
                "goal": "@{agent} perfect, now four more: ore belts at [gps={s4}], [gps={s5}], [gps={s6}] and "
                        "[gps={s7}], each with its chest at the bottom.",
                "answer": "Same design again. The chests are at [gps={c4}], [gps={c5}], [gps={c6}] and [gps={c7}].",
                "hold_samples": 2,
                "score": [{"name": "columns_working", "lua": columns([4, 5, 6, 7]), "target": 4}],
                "selftest": ladder_st([4, 5, 6, 7]), "wait": 90,
            },
        ],
    },
]


def build(sc: dict) -> dict:
    setup = COMMON + "\n" + (HERE / sc["setup"]).read_text()
    return {
        "name": sc["name"], "stage": STAGE, "minutes": sc["minutes"], "agents": 1, "kind": "directive",
        "group": "lab", "note": sc["note"], "setup_lua": setup,
        "objectives": [{"name": ob["name"], "minutes": ob.get("minutes", sc["minutes"]),
                        "hold_samples": ob.get("hold_samples", 2), "goal": ob["goal"], "answer": ob["answer"],
                        "score": ob["score"], "selftest_lua": ob["selftest"], "selftest_wait": ob.get("wait", 5)}
                       for ob in sc["objectives"]],
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
