local util = {}

local atan2 = math.atan2 or math.atan

function util.dist(a, b)
  local dx, dy = (a.x or a[1]) - (b.x or b[1]), (a.y or a[2]) - (b.y or b[2])
  return math.sqrt(dx * dx + dy * dy)
end

function util.pos(p)
  if not p then return nil end
  return { x = p.x or p[1], y = p.y or p[2] }
end

local function r1(v) return math.floor(v * 10 + 0.5) / 10 end

-- Compact [x, y] for output.
function util.xy(p) return { r1(p.x), r1(p.y) } end

-- 8-way walking direction toward (dx, dy). Factorio's y axis points south.
local OCTANTS = {
  [0] = "east", "southeast", "south", "southwest", "west", "northwest", "north", "northeast",
}
function util.walk_dir(dx, dy)
  local oct = math.floor((atan2(dy, dx) + math.pi / 8) / (math.pi / 4)) % 8
  return defines.direction[OCTANTS[oct]]
end

local DIR_NAMES = {}
for k, v in pairs(defines.direction) do DIR_NAMES[v] = k end
util.DIR_NAMES = DIR_NAMES

local OPPOSITE = { north = "south", south = "north", east = "west", west = "east" }
function util.opposite(name) return OPPOSITE[name] end
function util.opposite_dir(d) return (d + 8) % 16 end -- defines.direction has 16 steps in 2.0
function util.sign(v) return v > 0 and 1 or (v < 0 and -1 or 0) end

function util.parse_dir(d)
  if d == nil then return defines.direction.north end
  if type(d) == "number" then return d end
  return defines.direction[d] or defines.direction.north
end

local STATUS_NAMES = {}
for k, v in pairs(defines.entity_status) do STATUS_NAMES[v] = k end
util.STATUS_NAMES = STATUS_NAMES

-- { name = count } from a LuaInventory (2.0 get_contents returns a list).
function util.contents(inv)
  local out = {}
  if not (inv and inv.valid) then return out end
  for _, it in pairs(inv.get_contents()) do
    local key = it.name
    if it.quality and it.quality ~= "normal" then key = it.name .. "@" .. it.quality end
    out[key] = (out[key] or 0) + it.count
  end
  return out
end

-- Which side of `center` the point p is on: north/south/east/west (the dominant axis).
function util.side(center, p)
  local dx, dy = (p.x or p[1]) - (center.x or center[1]), (p.y or p[2]) - (center.y or center[2])
  if math.abs(dx) > math.abs(dy) then return dx > 0 and "east" or "west" end
  return dy > 0 and "south" or "north"
end

-- An inserter's pickup and drop sides in words, so its direction can't be read backwards.
function util.inserter_sides(e)
  return "picks from " .. util.side(e.position, e.pickup_position) .. ", drops " .. util.side(e.position, e.drop_position)
end

function util.watts(w)
  if w >= 1e9 then return string.format("%.1f GW", w / 1e9) end
  if w >= 1e6 then return string.format("%.1f MW", w / 1e6) end
  if w >= 1e3 then return string.format("%d kW", math.floor(w / 1e3 + 0.5)) end
  return string.format("%d W", math.floor(w + 0.5))
end

-- Electricity producers and wires: everything else with an electric energy source consumes.
local NOT_CONSUMERS = { ["electric-pole"] = true, generator = true, ["solar-panel"] = true, accumulator = true,
  ["electric-energy-interface"] = true, ["burner-generator"] = true, ["fusion-generator"] = true,
  ["lightning-attractor"] = true, ["power-switch"] = true }
util.NOT_CONSUMERS = NOT_CONSUMERS
function util.needs_power(e)
  if NOT_CONSUMERS[e.type] then return false end
  local ok, src = pcall(function() return e.prototype.electric_energy_source_prototype end)
  return ok and src ~= nil
end

-- The nearest pole on a grid that is producing power (the one to connect to), within r tiles.
function util.grid_pole(surface, force, p, r)
  local live = {}
  local best, bd
  for _, q in pairs(surface.find_entities_filtered { type = "electric-pole", force = force, position = p, radius = r or 64 }) do
    local id = q.electric_network_id
    if id and live[id] == nil then
      local made = 0
      local st = q.electric_network_statistics
      for name in pairs(st.output_counts) do
        made = made + st.get_flow_count { name = name, category = "output",
          precision_index = defines.flow_precision_index.five_seconds, count = false }
      end
      live[id] = made > 0
    end
    if id and live[id] then
      local d = util.dist(q.position, p)
      if not bd or d < bd then best, bd = q, d end
    end
  end
  return best, bd
end

-- The trees and rocks whose mining gives `item`, by prototype name. Wood comes only from some trees: on Vulcanus the
-- only trees are lichen, which give carbon (live test 25 Oct: every plan walked to one for wood that never came).
local gives = {}
function util.mined_for(item)
  if gives[item] then return gives[item] end
  local names = {}
  for name, p in pairs(prototypes.get_entity_filtered { { filter = "type", type = "tree" },
    { filter = "type", type = "simple-entity", mode = "or" } }) do
    local mp = p.mineable_properties
    for _, pr in pairs(mp and mp.minable and mp.products or {}) do
      if pr.name == item then names[#names + 1] = name break end
    end
  end
  gives[item] = names
  return names
end

-- How far a mining drill reaches from its centre (2.0 has it per quality; older names as a fallback).
function util.drill_radius(proto)
  local ok, r = pcall(function() return proto.get_mining_drill_radius() end)
  if ok and r then return r end
  ok, r = pcall(function() return proto.mining_drill_radius end)
  if ok and r then return r end
  local b = proto.collision_box
  return math.max(b.right_bottom.x - b.left_top.x, b.right_bottom.y - b.left_top.y) / 2
end

-- Whether a mining drill at p would have something it can mine in its area. A player can't place one where it
-- wouldn't (live test, 25 Oct: the serf's ghosts put drills off the calcite patch). True for anything else.
function util.drill_has_ore(surface, proto, p)
  if not proto or proto.type ~= "mining-drill" then return true end
  local r = util.drill_radius(proto)
  local cats = proto.resource_categories or {}
  for _, res in pairs(surface.find_entities_filtered { area = { { p.x - r, p.y - r }, { p.x + r, p.y + r } },
    type = "resource" }) do
    if cats[res.prototype.resource_category] then return true end
  end
  return false
end

-- "powered", "low power NN%", "no power: ..." for anything that runs on electricity; nil otherwise.
function util.power(e)
  if not util.needs_power(e) then return nil end
  local okC, on = pcall(function() return e.is_connected_to_electric_network() end)
  if okC and not on then
    local pole, d = util.grid_pole(e.surface, e.force, e.position)
    local okN, nid = pcall(function() return e.electric_network_id end)
    return (okN and nid and "no power: its poles don't reach any generator" or "no power: not on the grid") .. (pole and string.format(" (nearest grid pole %g,%g, %d tiles)",
      r1(pole.position.x), r1(pole.position.y), math.floor(d + 0.5)) or " (no powered pole within 64 tiles)")
  end
  local st = e.status
  if st == defines.entity_status.no_power then return "no power: its grid makes no electricity (inspect a pole)" end
  if st == defines.entity_status.low_power then
    local buf = e.electric_buffer_size
    return "low power" .. ((buf and buf > 0) and string.format(" %d%%", math.floor(e.energy / buf * 100)) or "")
  end
  return "powered"
end

function util.cheat()
  local s = settings.global["factorio-serf-cheat"]
  return s and s.value or false
end

-- Player-like name lookups.
function util.find_player(name)
  for _, p in pairs(game.players) do
    if p.name == name then return p end
  end
end

-- What a trigger tech wants done, in words a player would use.
function util.trigger_text(t)
  local trig = t.prototype.research_trigger
  if not trig then return nil end
  local what = trig.item and (type(trig.item) == "table" and trig.item.name or trig.item)
      or trig.entity or trig.tile or ""
  what = type(what) == "table" and (what.name or "?") or tostring(what)
  local n = trig.count and trig.count > 1 and (" x" .. trig.count) or ""
  local how = ""
  if trig.type == "mine-entity" and what == "crude-oil" then how = " (place a pumpjack on a crude-oil spot and power it)"
  elseif trig.type == "mine-entity" then how = " (mine it, or put a mining drill on it)"
  elseif trig.type == "craft-item" and (what:find("%-plate$") or what == "stone-brick") then
    how = " (smelt it in a furnace; hand-crafting can't make plates)"
  elseif trig.type == "craft-item" then how = " (craft it by hand or in an assembler)"
  elseif trig.type == "build-entity" then how = " (place one)"
  elseif trig.type == "craft-fluid" then how = " (produce it in a refinery/chemical plant)" end
  return trig.type .. " " .. what .. n .. how
end

return util
