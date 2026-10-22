#!/usr/bin/env python3
"""Validate the built-in blocks in jev/blueprints/ in a real game. No LLM involved.
(Ported from factorio-slave tests/test_blueprints.py @ a10f2ed.)

    .venv/bin/python tests/test_blocks.py                          # every block, rotations 0 and 90
    .venv/bin/python tests/test_blocks.py --designs red-science-5 --rotations 0,90,180,270 --jobs 2
    .venv/bin/python tests/test_blocks.py --offline                # static checks only (no server)
    .venv/bin/python tests/test_blocks.py --draft-dir /some/dir --designs my-new-block
        # try a draft block (a JSON file in that folder) without putting it in jev/blueprints/, where the
        # running planners would see it

1. Static checks (jev.blueprints.validate): grid snapping per footprint, overlaps, box, every rotation.
2. In game: isolated headless instances (scripts/instance.py, ids 60-69, at most 2 at once; localhost; the
   stage save is copied, never written; biters are removed at start) on --stage (default crew-test). Cases are spread over --jobs instances (one instance can host many
   cases far apart). Each case gets its own force (own research and power network) and:
   - finds a clear spot (surface.can_place_entity, manual build check, for the design AND the test harness, no
     other non-neutral entity within 4 tiles); designs with an anchor (the offshore pump) search the shore;
   - creates REAL entities with surface.create_entity at the stamped positions (and checks the game kept the
     position, direction and recipe), sets recipes; with --ghosts it instead lays entity-ghosts with recipes and
     revives them, which is what the mod's `blueprint` + `build_ghosts` ops do;
   - harness, all outside the design: per input belt lane an infinity chest -> loader -> belt that side-loads that
     lane; per output belt a loader into a steel chest (the count); chest inputs get an infinity chest; power from
     an electric-energy-interface on its own pole at least 3 tiles away (so it can't power anything the design's
     poles miss), wired to a design pole; for power designs the interface is a 1.8 MW load instead;
   - fluid inputs (ports with kind "fluid", e.g. sulfuric acid or lubricant): an infinity pipe just outside the
     port tile, on the port's side, full of that fluid; fluid outputs: an infinity pipe there that empties itself
     (a drain), except for fluids named in --blocked-outputs (to check that an unused output doesn't stall the
     block). Fluid output is measured as the case force's net production of that fluid (made minus used by the
     design's machines; infinity pipes don't count), so it equals what leaves through the port;
   - rocket parts (output kind "rocket-part"): counted from the force's item production; a finished rocket is
     launched at once so the silo keeps building;
   - output chests that are part of the design (output kind "chest", e.g. a mall): the count of that item in
     the design's own chest at the port tile;
   - research designs: the case force gets the test tech's prerequisites and that tech queued;
   - every case force gets the RECIPES below enabled (mid and late game: blue, purple and yellow science and
     everything they are made of). Recipes are given to create_entity, so an assembler with a fluid recipe keeps
     its direction (set_recipe afterwards would leave it facing north).
3. Warm up, then measure for --measure seconds of game time (default: the longest `measure_s` of the designs on
   that instance, at least 90; slow recipes such as blue packs finish in batches, so they need longer windows): output items (or research units, or MW), and each
   design entity's status every 10 s. Each case is judged on its own window (its `measure_s`, at least 90, from
   the shared start), so a lab row whose test tech would run out isn't spoiled by a slower neighbour.
PASS = measured >= 60% of the design's rated output, every entity placed where asked, and no entity in a bad
status for most samples (any: no power/fuel/recipe/fluid; producers: also ingredient shortage, output full,
missing packs; machines in test.may_idle may run short of fluid).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from jev import blueprints as bp  # noqa: E402
from jev.rcon import Crew, Rcon  # noqa: E402

PASS_FRACTION = 0.6
FIRST_INSTANCE = 60
SAMPLE_EVERY = 10.0

ALWAYS_BAD = {"no_power", "low_power", "no_fuel", "no_recipe", "not_plugged_in_electric_network", "disabled",
              "disabled_by_script", "marked_for_deconstruction", "no_input_fluid", "missing_required_fluid",
              "fluid_ingredient_shortage", "low_input_fluid", "low_temperature", "networks_disconnected",
              "recipe_not_researched"}
FLUID_SHORT = {"fluid_ingredient_shortage", "no_input_fluid", "missing_required_fluid", "low_input_fluid"}
PRODUCER_BAD = {"item_ingredient_shortage", "no_ingredients", "full_output", "waiting_for_space_in_destination",
                "no_research_in_progress", "missing_science_packs", "waiting_for_source_items", "no_minable_resources"}
RECIPES = ["automation-science-pack", "logistic-science-pack", "inserter", "transport-belt", "iron-gear-wheel",
           "electronic-circuit", "copper-cable", "iron-plate", "copper-plate", "stone-brick",
           "pipe", "steel-plate", "engine-unit", "plastic-bar", "sulfur", "advanced-circuit",
           "chemical-science-pack",
           # late game: purple and yellow science and their parts
           "production-science-pack", "rail", "iron-stick", "electric-furnace", "productivity-module",
           "utility-science-pack", "processing-unit", "low-density-structure", "flying-robot-frame",
           "electric-engine-unit", "battery", "lubricant", "sulfuric-acid",
           # oil, rocket fuel and the rocket
           "basic-oil-processing", "advanced-oil-processing", "heavy-oil-cracking", "light-oil-cracking",
           "solid-fuel-from-light-oil", "solid-fuel-from-petroleum-gas", "solid-fuel-from-heavy-oil", "rocket-fuel",
           "rocket-part",
           # malls: the buildings the serf places
           "underground-belt", "splitter", "assembling-machine-1", "electric-mining-drill", "small-electric-pole",
           "stone-furnace", "pipe-to-ground", "iron-chest", "wooden-chest", "long-handed-inserter", "fast-inserter"]
BLOCKED: set[str] = set()  # fluid outputs left without a drain (--blocked-outputs)
MEASURE_S = 90.0
INSTANCE_BLOCKS = ((60, 69),)  # ids this validator may start (campaigns and other experiments use the rest)
MAX_JOBS = 2  # the machine is shared: never more than 2 test servers at once


# ---------------------------------------------------------------------------- draft designs
def use_draft_dir(folder: Path) -> None:
    """Designs in `folder` (name.json) are found first, ahead of jev/blueprints/ (this process only)."""
    orig_path, orig_names = bp._path, bp.names

    def _path(name: str) -> Path:
        p = folder / f"{name}.json"
        return p if p.exists() else orig_path(name)

    def names() -> list[str]:
        return sorted(set(orig_names()) | {p.stem for p in folder.glob("*.json")})
    bp._path, bp.names = _path, names


# ---------------------------------------------------------------------------- harness layout (design frame)
def _left(d: str) -> str:
    return bp.rotate_dir(d, 3)


def _right(d: str) -> str:
    return bp.rotate_dir(d, 1)


def _add(p, d, n=1):
    v = bp.VEC[d]
    return (p[0] + v[0] * n, p[1] + v[1] * n)


def _ent(name, tile, direction="north", **kw):
    return {"name": name, "x": tile[0] + 0.5, "y": tile[1] + 0.5, "direction": direction, **kw}


def harness_layout(design: dict) -> list[dict]:
    """Test-only entities around the design, in the design's own (unrotated) frame."""
    out: list[dict] = []
    for port in design.get("inputs", []):
        t = tuple(port["at"])
        if port.get("kind") == "chest":
            out.append(_ent("infinity-chest", t, role="source", item=port["item"]))
            continue
        if port.get("kind") == "fluid":  # an infinity pipe just outside, on the side the pipe comes from
            out.append(_ent("infinity-pipe", _add(t, port["side"], 1), role="fluid_source", fluid=port["fluid"]))
            continue
        d = bp.opposite(port["side"])          # items flow into the design
        p = _add(t, d, -1)                     # feeder tile just outside, flowing in
        out.append(_ent("transport-belt", p, d, role="feed"))
        out.append(_ent("transport-belt", _add(p, d, -1), d, role="feed"))  # rear belt: keeps p straight (side-load)
        for lane, item in port.get("lanes", {}).items():
            side = _left(d) if lane == "left" else _right(d)
            toward = bp.opposite(side)
            out.append(_ent("transport-belt", _add(p, side, 1), toward, role="feed"))
            out.append(_ent("loader-1x1", _add(p, side, 2), toward, role="feed", loader_type="output"))
            out.append(_ent("infinity-chest", _add(p, side, 3), role="source", item=item))
    for port in design.get("outputs", []):
        if "at" not in port or port.get("kind") in ("power", "research", "rocket-part", "chest"):
            continue
        if port.get("kind") == "fluid":  # a drain just outside, on the port's side
            if port["fluid"] not in BLOCKED:
                out.append(_ent("infinity-pipe", _add(tuple(port["at"]), port["side"], 1), role="fluid_sink",
                                fluid=port["fluid"]))
            continue
        d = port["side"]
        t = tuple(port["at"])
        out.append(_ent("loader-1x1", _add(t, d, 1), d, role="sink_loader", loader_type="input"))
        out.append(_ent("steel-chest", _add(t, d, 2), role="sink",
                        items=[port["item"]] + list(port.get("also", {}))))
    if any(e["name"].endswith("electric-pole") for e in design["entities"]):
        out += _power_spot(design, out)
    return out


def _power_spot(design: dict, harness: list[dict]) -> list[dict]:
    """EEI + pole in a free corner, the pole >= 3 tiles outside the box so its supply area can't reach the design."""
    w, h = design["size"]
    used = set()
    for e in harness:
        used.update(bp.footprint_tiles(e))
    load = any(p.get("kind") == "power" for p in design.get("outputs", []))
    corners = [((-3, -3), (-4, -4)), ((w + 2, -3), (w + 4, -4)), ((-3, h + 2), (-4, h + 4)),
               ((w + 2, h + 2), (w + 4, h + 4))]
    if design.get("test", {}).get("anchor"):  # shore designs: the water is north of the pump, so go south
        corners = corners[2:] + corners[:2]
    for pole, eei in corners:
        ents = [_ent("small-electric-pole", pole, role="power_pole"),
                {"name": "electric-energy-interface", "x": eei[0], "y": eei[1], "direction": "north",
                 "role": "load" if load else "power"}]
        tiles = set()
        for e in ents:
            tiles.update(bp.footprint_tiles(e))
        grown = {(x + dx, y + dy) for x, y in tiles for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        if not grown & used:
            return ents
    raise RuntimeError(f"{design['name']}: no free corner for the power harness")


def case_spec(name: str, rotation: int) -> dict:
    """Design + harness entities rotated about the design origin (top-left of the rotated design at 0,0)."""
    d = bp.get_design(name)
    steps = bp.rotation_steps(rotation)
    w, h = d["size"]
    st = bp.stamp(name, 0, 0, rotation)
    design_ents = st["entities"]
    harness = []
    for e in harness_layout(d):
        x, y = bp.rotate_point(e["x"], e["y"], w, h, steps)
        harness.append({**e, "x": x, "y": y, "direction": bp.rotate_dir(e["direction"], steps)})
    tiles = [t for e in design_ents + harness for t in bp.footprint_tiles(e)]
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    spec = {"name": name, "rotation": steps * 90, "design": design_ents, "harness": harness,
            "box": [min(xs), min(ys), max(xs) + 1, max(ys) + 1], "test": d.get("test", {}),
            "outputs": st["outputs"], "rw": st["size"][0], "rh": st["size"][1]}
    anchor = d.get("test", {}).get("anchor")
    if anchor:
        a = next(e for e in design_ents if e["name"] == anchor)
        spec["anchor"] = {"name": anchor, "x": a["x"], "y": a["y"], "direction": a["direction"]}
    return spec


# ---------------------------------------------------------------------------- Lua
PRELUDE = r"""
local s = game.surfaces.nauvis
local D = defines.direction
local function dir(n) return D[n or "north"] end
local function fits(f, list, ox, oy)
  for _, e in ipairs(list) do
    if not s.can_place_entity { name = e.name, position = { ox + e.x, oy + e.y }, direction = dir(e.direction),
        force = f, build_check_type = defines.build_check_type.manual } then return false end
  end
  return true
end
local function clear(spec, ox, oy, m)
  local b = spec.box
  for _, c in ipairs { { b[1], b[2] }, { b[3], b[2] }, { b[1], b[4] }, { b[3], b[4] } } do
    if not s.is_chunk_generated { math.floor((ox + c[1]) / 32), math.floor((oy + c[2]) / 32) } then return false end
  end
  return s.count_entities_filtered { area = { { ox + b[1] - m, oy + b[2] - m }, { ox + b[3] + m, oy + b[4] + m } },
    force = "neutral", invert = true } == 0
end
"""

SETUP = PRELUDE + r"""
s.peaceful_mode = true
game.forces.enemy.kill_all_units()
storage.bp_test = {}
local c = game.forces.player.get_spawn_position(s)
return { spawn = { c.x, c.y } }
"""

PLACE = PRELUDE + r"""
local spec = helpers.json_to_table([==[%s]==])
local fname = "bpt-" .. spec.case
local f = game.forces[fname] or game.create_force(fname)
for _, r in ipairs(spec.recipes) do if f.recipes[r] then f.recipes[r].enabled = true end end
local all = {}
for _, e in ipairs(spec.design) do all[#all + 1] = e end
for _, e in ipairs(spec.harness) do all[#all + 1] = e end
local C = spec.center
local ox, oy
if spec.anchor then
  local tiles = s.find_tiles_filtered { position = C, radius = 400, collision_mask = "water_tile", limit = 40000 }
  table.sort(tiles, function(a, b) return util.dist(a.position, C) < util.dist(b.position, C) end)
  local tried = 0
  for i = 1, #tiles do
    local t = tiles[i]
    for _, off in ipairs { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } } do
      local px, py = t.position.x + off[1] + 0.5, t.position.y + off[2] + 0.5
      if s.can_place_entity { name = spec.anchor.name, position = { px, py }, direction = dir(spec.anchor.direction),
          force = f, build_check_type = defines.build_check_type.manual } then
        tried = tried + 1
        local cx, cy = px - spec.anchor.x, py - spec.anchor.y
        if clear(spec, cx, cy, 4) and fits(f, all, cx, cy) then ox, oy = cx, cy break end
      end
    end
    if ox then break end
  end
  if not ox then return { error = "no shore spot fits (tried " .. tried .. " pump spots)" } end
else
  local step = 3
  for r = 0, 240, step do
    local pts = { { 0, 0 } }
    if r > 0 then
      pts = {}
      for d = -r, r, step do pts[#pts + 1] = { d, -r } pts[#pts + 1] = { d, r } end
      for d = -r + step, r - step, step do pts[#pts + 1] = { -r, d } pts[#pts + 1] = { r, d } end
    end
    for _, pt in ipairs(pts) do
      local cx, cy = math.floor(C[1] + pt[1]), math.floor(C[2] + pt[2])
      if clear(spec, cx, cy, 4) and fits(f, all, cx, cy) then ox, oy = cx, cy break end
    end
    if ox then break end
  end
  if not ox then return { error = "no clear spot within 240 tiles" } end
end
-- types whose direction matters (2 = symmetric, either way along the axis is the same machine)
local ORIENTED = { inserter = 1, ["transport-belt"] = 1, ["underground-belt"] = 1, splitter = 1, boiler = 1,
  ["offshore-pump"] = 1, ["mining-drill"] = 1, ["loader-1x1"] = 1, generator = 2, pump = 1,
  ["pipe-to-ground"] = 1, ["storage-tank"] = 2 }
local function fluid_recipe(r)
  local p = r and prototypes.recipe[r]
  if not p then return false end
  for _, i in ipairs(p.ingredients) do if i.type == "fluid" then return true end end
  for _, i in ipairs(p.products) do if i.type == "fluid" then return true end end
  return false
end
local reg = { force = fname, design = {}, engines = {}, silos = {}, stats = spec.stats or {}, chests = spec.chests or {} }
local bad = {}
local function make(e, is_design)
  local want = { x = ox + e.x, y = oy + e.y }
  local spec2 = { name = e.name, position = want, direction = dir(e.direction), force = f }
  if e.loader_type then spec2.type = e.loader_type end
  if e.recipe then spec2.recipe = e.recipe end  -- at creation, so a fluid recipe keeps the asked direction
  local ent
  if spec.ghosts and is_design then  -- the agents' path: entity-ghost (+recipe), then revive
    local okg, g = pcall(s.create_entity, { name = "entity-ghost", inner_name = e.name, position = want,
      direction = dir(e.direction), force = f, expires = false })
    if okg and g then
      if e.recipe then pcall(function() g.set_recipe(e.recipe) end) end
      local _, revived = g.revive { raise_revive = false }
      ent = revived
    end
  else
    ent = s.create_entity(spec2)
  end
  if not ent then bad[#bad + 1] = "could not create " .. e.name .. " at " .. want.x .. "," .. want.y return end
  if math.abs(ent.position.x - want.x) > 0.01 or math.abs(ent.position.y - want.y) > 0.01 then
    bad[#bad + 1] = e.name .. " asked at " .. want.x .. "," .. want.y .. " landed at " .. ent.position.x .. "," .. ent.position.y
  end
  local oriented = ORIENTED[ent.type]
  if (ent.type == "assembling-machine" or ent.type == "furnace") and fluid_recipe(e.recipe) then oriented = 1 end
  if is_design and oriented and ent.direction ~= dir(e.direction)
      and not (oriented == 2 and ent.direction == (dir(e.direction) + 8) %% 16) then
    bad[#bad + 1] = e.name .. " at " .. want.x .. "," .. want.y .. " faces " .. util.DIR_NAMES[ent.direction] .. " not " .. e.direction
  end
  if e.recipe and not (spec.ghosts and is_design) and not (ent.get_recipe() and ent.get_recipe().name == e.recipe) then
    local okr, err = pcall(function() ent.set_recipe(e.recipe) end)
    if not okr then bad[#bad + 1] = "set_recipe " .. e.recipe .. ": " .. tostring(err) end
  end
  if e.recipe then
    local r = ent.get_recipe()
    if not (r and r.name == e.recipe) then bad[#bad + 1] = e.name .. " at " .. want.x .. "," .. want.y .. " has no recipe " .. e.recipe end
  end
  if is_design then
    reg.design[#reg.design + 1] = ent
    if ent.type == "generator" then reg.engines[#reg.engines + 1] = ent end
    if ent.type == "electric-pole" then reg.pole = reg.pole or ent end
    if ent.type == "rocket-silo" then reg.silos[#reg.silos + 1] = ent end
  end
  if e.role == "source" then ent.set_infinity_container_filter(1, { name = e.item, count = 100, mode = "exactly" }) end
  if e.role == "fluid_source" then ent.set_infinity_pipe_filter { name = e.fluid, percentage = 1, mode = "at-least" } end
  if e.role == "fluid_sink" then ent.set_infinity_pipe_filter { name = e.fluid, percentage = 0, mode = "at-most" } end
  if e.role == "sink" then reg.sink, reg.items = ent, e.items end
  if e.role == "power_pole" then reg.hpole = ent end
  if e.role == "power" then
    ent.power_production = 1e9 / 60 ent.power_usage = 0 ent.electric_buffer_size = 1e9 / 30
  elseif e.role == "load" then
    ent.power_production = 0 ent.power_usage = 1.8e6 / 60 ent.electric_buffer_size = 1.8e6 / 60 * 4
    reg.load = ent
  end
end
for _, e in ipairs(spec.design) do make(e, true) end
for _, e in ipairs(spec.harness) do make(e, false) end
if reg.hpole and reg.pole then
  local a = reg.hpole.get_wire_connector(defines.wire_connector_id.pole_copper, true)
  a.connect_to(reg.pole.get_wire_connector(defines.wire_connector_id.pole_copper, true), false)
end
if spec.research then
  local t = f.technologies[spec.research]
  local function done(tt) for _, p in pairs(tt.prerequisites) do if not p.researched then done(p) p.researched = true end end end
  done(t)
  f.laboratory_speed_modifier = 0
  local okq = pcall(function() f.add_research(t) end)
  if not okq or not f.current_research then pcall(function() f.research_queue = { t } end) end
  reg.tech = spec.research
  reg.queued = f.current_research and f.current_research.name or "none"
end
storage.bp_test[spec.case] = reg
return { origin = { ox, oy }, problems = bad, queued = reg.queued, n = #reg.design }
"""

SAMPLE = r"""
local out = {}
for case, c in pairs(storage.bp_test) do
  local r = { tick = game.tick, st = {} }
  if c.sink and c.sink.valid then
    r.out = {}
    for _, it in ipairs(c.items) do r.out[it] = c.sink.get_item_count(it) end
  end
  local f = game.forces[c.force]
  if c.tech then
    local t = f.technologies[c.tech]
    r.units_total = t.research_unit_count
    if t.researched then r.units = t.research_unit_count
    elseif f.current_research and f.current_research.name == c.tech then r.units = f.research_progress * t.research_unit_count
    else r.units = (t.saved_progress or 0) * t.research_unit_count end
  end
  if #c.engines > 0 then
    local w = 0
    for _, e in ipairs(c.engines) do if e.valid then w = w + e.energy_generated_last_tick * 60 end end
    r.mw = w / 1e6
  end
  for i, e in ipairs(c.design) do
    if e.valid and e.status then r.st["e" .. i] = util.STATUS_NAMES[e.status] or tostring(e.status) end
  end
  if c.chests and #c.chests > 0 then
    r.out = r.out or {}
    for _, ch in ipairs(c.chests) do
      local e = c.design[ch.i]
      if e and e.valid then r.out[ch.item] = (r.out[ch.item] or 0) + e.get_item_count(ch.item) end
    end
  end
  if c.stats and #c.stats > 0 then
    r.stat = {}
    local fs = f.get_fluid_production_statistics(game.surfaces.nauvis)
    local is = f.get_item_production_statistics(game.surfaces.nauvis)
    for _, m in ipairs(c.stats) do
      if m.kind == "fluid" then r.stat[m.name] = fs.get_input_count(m.name) - fs.get_output_count(m.name)
      else r.stat[m.name] = is.get_input_count(m.name) end
    end
  end
  for _, sl in ipairs(c.silos or {}) do  -- keep the silo building: launch a finished rocket at once
    if sl.valid and sl.rocket_silo_status == defines.rocket_silo_status.rocket_ready then
      local ok = pcall(function() sl.launch_rocket() end)
      r.launches = (r.launches or 0) + (ok and 1 or 0)
    end
  end
  out[case] = r
end
return out
"""


async def ev(crew: Crew, code: str, timeout: float = 120):
    res = await asyncio.wait_for(crew.call("eval", code=code), timeout)
    return res.get("result") if isinstance(res, dict) else res


# ---------------------------------------------------------------------------- one instance, several cases
class Case:
    def __init__(self, name: str, rotation: int, idx: int, ghosts: bool = False):
        self.name, self.rotation, self.idx, self.ghosts = name, rotation, idx, ghosts
        self.key = f"{idx}"
        self.spec = case_spec(name, rotation)
        self.test = self.spec["test"]
        self.origin = None
        self.problems: list[str] = []
        self.samples: list[dict] = []
        out = (self.spec["outputs"] or [{}])[0]
        self.kind = out.get("kind", "items")
        self.rated = float(out.get("rate", 0))
        self.rates = {out["item"]: self.rated, **out.get("also", {})} if out.get("item") else {}
        # fluid outputs and rocket parts are counted from the force's production statistics
        self.stats = []
        for o in self.spec["outputs"]:
            if o.get("kind") == "fluid" and o["fluid"] not in BLOCKED:
                self.stats.append({"name": o["fluid"], "kind": "fluid"})
                self.rates[o["fluid"]] = float(o["rate"])
            elif o.get("kind") == "rocket-part":
                self.stats.append({"name": "rocket-part", "kind": "item"})
                self.rates["rocket-part"] = float(o["rate"])
        # design chests at output ports (kind "chest"): index into the design's entity list
        self.chests = []
        for o in self.spec["outputs"]:
            if o.get("kind") == "chest":
                at = tuple(o["at"])
                idx = next((i for i, e in enumerate(self.spec["design"]) if at in bp.footprint_tiles(e)), None)
                if idx is None:
                    raise ValueError(f"{name}: no design chest at output tile {at}")
                self.chests.append({"i": idx + 1, "item": o["item"]})
                self.rates[o["item"]] = float(o["rate"])
        if self.kind in ("fluid", "rocket-part", "chest"):
            self.kind = "items"
            first = next(iter(self.rates), None)
            self.rated = self.rates[first] if first else 0.0
        self.unit = {"items": "/s", "research": " units/s", "power": " MW"}.get(self.kind, "")
        self.error: str | None = None
        self.window: float | None = None  # this case's own measuring time (s); the instance may measure longer

    def measured_samples(self) -> list[dict]:
        """Samples within this case's own window from the shared start: a short test (e.g. a lab row whose tech
        runs out) isn't spoiled by a longer neighbour on the same instance."""
        if not self.window or not self.samples:
            return self.samples
        lim = self.samples[0]["tick"] + self.window * 60 + 60
        return [s for s in self.samples if s["tick"] <= lim]

    def place_lua(self, center) -> str:
        spec = {"case": self.key, "design": self.spec["design"], "harness": self.spec["harness"],
                "box": self.spec["box"], "center": center, "recipes": RECIPES,
                "anchor": self.spec.get("anchor"), "research": self.test.get("research"), "ghosts": self.ghosts,
                "stats": self.stats, "chests": self.chests}
        return PLACE % json.dumps(spec, separators=(",", ":"))

    def may_idle(self, e: dict) -> bool:
        """test.may_idle: machines that only work on surplus (e.g. oil crackers while every output is drawn), so
        running short of fluid is fine for them."""
        for p in self.test.get("may_idle", []):
            n, _, r = p.partition(":")
            if e["name"] == n and (not r or e.get("recipe") == r):
                return True
        return False

    def producer(self, e: dict) -> bool:
        for p in self.test.get("producers", []):
            n, _, r = p.partition(":")
            if e["name"] == n and (not r or e.get("recipe") == r):
                return True
        return False

    def result(self) -> dict:
        res = {"design": self.name, "rotation": self.rotation, "origin": self.origin, "rated": self.rated,
               "mode": "ghosts" if self.ghosts else "create_entity",
               "unit": self.unit, "problems": list(self.problems), "error": self.error}
        samples = self.measured_samples()
        if self.error or len(samples) < 2:
            res.update(measured=None, ratio=0.0, ok=False)
            if not self.error:
                res["error"] = "not enough samples"
            return res
        a, b = samples[0], samples[-1]
        dt = (b["tick"] - a["tick"]) / 60
        if self.kind == "research":
            measured = (b.get("units", 0) - a.get("units", 0)) / dt
        elif self.kind == "power":
            vals = [s.get("mw", 0) for s in samples]
            measured = sum(vals) / len(vals)
        else:
            def got(smp, it):
                if it in (smp.get("stat") or {}):
                    return smp["stat"][it]
                return (smp.get("out") or {}).get(it, 0)
            per = {it: (got(b, it) - got(a, it)) / dt for it in self.rates}
            measured = per[next(iter(self.rates))]
            res["per_item"] = {it: f"{v:.3g}/{self.rates[it]:g}" for it, v in per.items()}
        bad: dict[int, list[str]] = {}
        n = len(samples)
        ents = self.spec["design"]
        for i, e in enumerate(ents, 1):
            sts = [s["st"].get(f"e{i}") for s in samples if isinstance(s.get("st"), dict)]
            sts = [x for x in sts if x]
            if not sts:
                continue
            badset = ALWAYS_BAD | (PRODUCER_BAD if self.producer(e) else set())
            if self.may_idle(e):
                badset = badset - FLUID_SHORT
            nb = sum(1 for x in sts if x in badset)
            if nb * 2 > len(sts):
                worst = max(set(sts), key=sts.count)
                bad[i] = [e["name"], f"({e['x']},{e['y']})", f"{worst} {nb}/{len(sts)}"]
        res["stuck"] = [" ".join(v) for v in bad.values()]
        res["status_counts"] = self._status_counts()
        res["measured"] = round(measured, 3)
        res["ratio"] = round(measured / self.rated, 2) if self.rated else 0.0
        if res.get("per_item"):  # every output item must make its own rate
            res["ratio"] = round(min(per[it] / r for it, r in self.rates.items() if r), 2)
        res["seconds"] = round(dt, 1)
        res["samples"] = n
        res["ok"] = (res["ratio"] >= PASS_FRACTION and not res["stuck"] and not res["problems"])
        return res

    def _status_counts(self) -> dict:
        out: dict[str, dict[str, int]] = {}
        for i, e in enumerate(self.spec["design"], 1):
            for s in self.measured_samples():
                st = (s.get("st") or {}).get(f"e{i}") if isinstance(s.get("st"), dict) else None
                if st:
                    k = e["name"] + (":" + e["recipe"] if e.get("recipe") else "")
                    out.setdefault(k, {})
                    out[k][st] = out[k].get(st, 0) + 1
        return out


def _reap(inst) -> None:
    """If the server this run started is still alive after inst.stop() (seen once: a start judged failed while the
    server came up anyway, so stop() found no pid and the server was left running), interrupt it directly."""
    proc = getattr(inst, "proc", None)
    if proc is None or proc.poll() is not None:
        return
    import signal
    for sig, wait in ((signal.SIGINT, 30), (signal.SIGKILL, 5)):
        try:
            proc.send_signal(sig)
            proc.wait(wait)
            return
        except Exception:  # noqa: BLE001
            continue


async def run_group(k: int, cases: list[Case], args) -> None:
    from instance import Instance
    inst = Instance(k, args.stage)
    rcon = None
    t0 = time.time()
    try:
        print(f"[i{k}] starting instance {k} on {args.stage} for {len(cases)} case(s)", flush=True)
        await asyncio.to_thread(inst.start, 240)
        rcon = Rcon(inst.host, inst.rcon_port, inst.password)
        await rcon.connect()
        crew = Crew(rcon)
        setup = await ev(crew, SETUP)
        center = setup["spawn"]
        for c in cases:
            r = await ev(crew, c.place_lua(center), 180)
            if r.get("error"):
                c.error = r["error"]
                print(f"[i{k}] {c.name} rot {c.rotation}: {c.error}", flush=True)
                continue
            c.origin = r["origin"]
            c.problems = r.get("problems") or []
            print(f"[i{k}] placed {c.name} rot {c.rotation} at {c.origin} ({r.get('n')} entities)"
                  + (f" research={r.get('queued')}" if c.test.get("research") else "")
                  + (f" PROBLEMS {c.problems}" if c.problems else ""), flush=True)
        live = [c for c in cases if not c.error]
        warm = args.warmup if args.warmup is not None else max([c.test.get("warmup_s", 30) for c in live] or [0])
        measure = args.measure if args.measure is not None else max(
            [MEASURE_S] + [float(c.test.get("measure_s", MEASURE_S)) for c in live])
        for c in live:
            c.window = args.measure if args.measure is not None else max(
                MEASURE_S, float(c.test.get("measure_s", MEASURE_S)))
        print(f"[i{k}] warming up {warm:.0f}s, then measuring {measure:.0f}s", flush=True)
        await asyncio.sleep(warm)
        end = time.time() + measure
        while True:
            snap = await ev(crew, SAMPLE)
            for c in live:
                if isinstance(snap, dict) and c.key in snap:
                    c.samples.append(snap[c.key])
            if time.time() >= end:
                break
            await asyncio.sleep(min(SAMPLE_EVERY, max(0.5, end - time.time())))
    except Exception as e:  # noqa: BLE001
        for c in cases:
            c.error = c.error or f"instance {k}: {e!r}"[:300]
        print(f"[i{k}] failed: {e!r}\n{inst.tail(15)}", flush=True)
    finally:
        if rcon:
            await rcon.close()
        await asyncio.to_thread(inst.stop)
        await asyncio.to_thread(_reap, inst)
        print(f"[i{k}] stopped ({time.time() - t0:.0f}s)", flush=True)


# ---------------------------------------------------------------------------- report
def table(results: list[dict]) -> str:
    rows = [("design", "rot", "origin", "measured", "rated", "%", "result", "notes")]
    for r in results:
        notes = r.get("error") or "; ".join((r.get("problems") or []) + (r.get("stuck") or []))
        if r.get("per_item") and len(r["per_item"]) > 1:
            notes = ("per item " + ", ".join(f"{k} {v}" for k, v in r["per_item"].items()) + " " + notes).strip()
        meas = "-" if r.get("measured") is None else f"{r['measured']:.3g}{r['unit']}"
        rows.append((r["design"], str(r["rotation"]), str(r.get("origin") or "-"), meas,
                     f"{r['rated']:g}{r['unit']}", f"{round(100 * r['ratio'])}", "PASS" if r["ok"] else "FAIL",
                     notes[:120]))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    out = []
    for row in rows:
        out.append("  ".join(c.ljust(w) for c, w in zip(row[:-1], widths)) + "  " + row[-1])
    return "\n".join(out)


def offline_checks(designs: list[str]) -> list[str]:
    probs = []
    for n in designs:
        probs += bp.validate(n)
        d = bp.get_design(n)
        for rot in (0, 90, 180, 270):  # harness must not collide with the design either
            spec = case_spec(n, rot)
            probs += [f"[{n} rot {rot} +harness] {p}" for p in bp.check_layout(spec["design"] + spec["harness"])]
        if not d.get("description") or not d.get("entities"):
            probs.append(f"[{n}] missing description/entities")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", help="comma list (default: all)")
    ap.add_argument("--rotations", default="0,90")
    ap.add_argument("--stage", default="crew-test", help="save in server/factorio/saves (copied, never written)")
    ap.add_argument("--jobs", type=int, default=1,
                    help=f"instances in parallel (ids first-instance.., at most {MAX_JOBS})")
    ap.add_argument("--first-instance", type=int, default=FIRST_INSTANCE,
                    help="first instance id: 60..69 (default 60)")
    ap.add_argument("--draft-dir", help="also look for designs here (draft blocks not yet in jev/blueprints/)")
    ap.add_argument("--blocked-outputs", default="",
                    help="comma list of fluids whose output ports get no drain (check that an unused output doesn't "
                         "stall the block; those fluids aren't measured)")
    ap.add_argument("--warmup", type=float, default=None, help="seconds before measuring (default: per design)")
    ap.add_argument("--measure", type=float, default=None,
                    help=f"seconds of measurement (default: per design `measure_s`, at least {MEASURE_S:g})")
    ap.add_argument("--offline", action="store_true", help="static checks only")
    ap.add_argument("--ghosts", action="store_true",
                    help="build the design the agents' way: entity-ghosts with recipes, then revive them")
    ap.add_argument("--json", help="write results here")
    ap.add_argument("-v", "--verbose", action="store_true", help="print status counts per case")
    args = ap.parse_args()

    if args.draft_dir:
        use_draft_dir(Path(args.draft_dir))
    BLOCKED.update(f for f in args.blocked_outputs.split(",") if f)
    designs = args.designs.split(",") if args.designs else bp.names()
    probs = offline_checks(designs)
    print(f"static checks: {len(designs)} designs x 4 rotations: " + ("OK" if not probs else f"{len(probs)} problems"))
    for p in probs:
        print("  " + p)
    if probs:
        return 1
    if args.offline:
        return 0

    rots = [int(r) for r in args.rotations.split(",")]
    cases = [Case(n, r, i, args.ghosts) for i, (n, r) in enumerate((n, r) for n in designs for r in rots)]
    block = next((b for b in INSTANCE_BLOCKS if b[0] <= args.first_instance <= b[1]), None)
    if not block:
        ap.error("--first-instance must be 60..69")
    jobs = max(1, min(args.jobs, MAX_JOBS, block[1] + 1 - args.first_instance, len(cases)))
    groups = [cases[j::jobs] for j in range(jobs)]

    async def go():
        await asyncio.gather(*(run_group(args.first_instance + j, g, args) for j, g in enumerate(groups)))
    asyncio.run(go())

    results = [c.result() for c in cases]
    print()
    print(table(results))
    if args.verbose:
        for r in results:
            print(f"\n{r['design']} rot {r['rotation']}: {json.dumps(r.get('status_counts'))}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1))
    ok = sum(r["ok"] for r in results)
    print(f"\n{ok}/{len(results)} passed (pass = >= {int(PASS_FRACTION * 100)}% of rated output, nothing stuck)")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
