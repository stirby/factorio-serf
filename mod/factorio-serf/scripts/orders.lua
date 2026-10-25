-- Read-only queries for the order system (docs/architecture.md): what an order's zone still needs, where to get
-- items, and whether an order's done_when check passes. The controller and scheduler call these; no model does.
local util = require("scripts.util")

local orders = {}

local function surface_of(req)  -- the named surface, else the agent's planet, else nauvis
  local s = req.surface and game.surfaces[req.surface]
  if s then return s end
  local a = req.agent and storage.agents[req.agent]
  if a and a.char and a.char.valid then return a.char.surface end
  return game.surfaces.nauvis
end

local function area_of(req)
  local z = req.zone or { req.x1, req.y1, req.x2, req.y2 }
  return { { math.min(z[1], z[3]), math.min(z[2], z[4]) }, { math.max(z[1], z[3]), math.max(z[2], z[4]) } }
end

local function ghost_items(g)
  local out = {}
  for _, it in pairs(g.ghost_prototype.items_to_place_this or {}) do
    out[#out + 1] = { name = it.name, count = it.count or 1 }
  end
  return out
end

-- What the zone still needs: unbuilt ghosts (and the items they take), things marked for removal in the way, and
-- burner machines that are out of (or low on) fuel.
function orders.zone(req)
  local s, f = surface_of(req), game.forces.player
  local area = area_of(req)
  local ghosts = s.find_entities_filtered { area = area, type = "entity-ghost", force = f }
  local needs, by_name, at = {}, {}, {}
  for _, g in ipairs(ghosts) do
    for _, it in ipairs(ghost_items(g)) do needs[it.name] = (needs[it.name] or 0) + it.count end
    by_name[g.ghost_name] = (by_name[g.ghost_name] or 0) + 1
    if #at < 8 then at[#at + 1] = util.xy(g.position) end
  end
  local blockers = {}
  for _, e in ipairs(s.find_entities_filtered { area = area, to_be_deconstructed = true }) do
    if #blockers < 40 then blockers[#blockers + 1] = { name = e.name, p = util.xy(e.position) } end
  end
  local fuel = {}
  for _, e in ipairs(s.find_entities_filtered { area = area, force = f }) do
    local b = e.burner
    if b and e.type ~= "character" and e.type ~= "car" and e.type ~= "locomotive" then
      local inv = b.inventory
      local n = inv and inv.get_item_count() or 0
      if n < 5 and #fuel < 40 then fuel[#fuel + 1] = { name = e.name, p = util.xy(e.position), fuel = n } end
    end
  end
  return { ghosts = #ghosts, needs = needs, by_name = by_name, ghost_at = at, blockers = blockers,
    low_fuel = fuel, center = { (area[1][1] + area[2][1]) / 2, (area[1][2] + area[2][2]) / 2 } }
end

-- Chests holding the items, nearest first (to `x,y`), skipping chests inside `exclude` (the order's own zone).
function orders.sources(req)
  local s, f = surface_of(req), game.forces.player
  local cx, cy, r = req.x or 0, req.y or 0, req.radius or 400
  local ex = req.exclude and area_of({ zone = req.exclude }) or nil
  local chests = s.find_entities_filtered { type = { "container", "logistic-container", "infinity-container",
    "furnace", "assembling-machine" }, force = f, position = { cx, cy }, radius = r }
  local out, totals = {}, {}
  for _, name in ipairs(req.items or {}) do
    local list = {}
    for _, c in ipairs(chests) do
      local p = c.position
      local inside = ex and p.x >= ex[1][1] and p.x <= ex[2][1] and p.y >= ex[1][2] and p.y <= ex[2][2]
      if not inside and c.operable then  -- a locked chest isn't storage anyone can take from
        local n
        if c.type == "furnace" or c.type == "assembling-machine" then
          local out = c.get_output_inventory()  -- only finished products, never a machine's ingredients
          n = out and out.get_item_count(name) or 0
        else
          n = c.get_item_count(name)
        end
        if n > 0 then
          list[#list + 1] = { p = util.xy(p), n = n, d = math.floor(math.sqrt((p.x - cx) ^ 2 + (p.y - cy) ^ 2)),
            ["in"] = c.name }
        end
      end
    end
    table.sort(list, function(a, b) return a.d < b.d end)
    local total = 0
    for _, l in ipairs(list) do total = total + l.n end
    totals[name] = total
    while #list > (req.limit or 5) do table.remove(list) end
    out[name] = list
  end
  return { sources = out, totals = totals }
end

-- done_when conditions. Each returns ok, value.
local CHECKS = {}
CHECKS.ghosts_cleared = function(s, area)
  local n = s.count_entities_filtered { area = area, type = "entity-ghost", force = game.forces.player }
  return n == 0, n
end
CHECKS.working = function(s, area, c)
  local filt = { force = game.forces.player }
  if c.scope ~= "base" then filt.area = area end
  if c.name then filt.name = c.name end
  local n, total = 0, 0
  for _, e in ipairs(s.find_entities_filtered(filt)) do
    total = total + 1
    local okS, st = pcall(function() return e.status end)
    if okS and st == defines.entity_status.working then n = n + 1 end
  end
  if total < (c.min or 1) then
    return false, n, "asks for " .. (c.min or 1) .. " but there are only " .. total .. " in " .. (filt.area and "the zone" or "the base")
  end
  return n >= (c.min or 1), n
end
CHECKS.exists = function(s, area, c)
  local filt = { force = game.forces.player, name = c.name }
  if c.scope ~= "base" then filt.area = area end
  local n = s.count_entities_filtered(filt)
  return n >= (c.min or 1), n
end
CHECKS.rate = function(s, area, c)
  local st = game.forces.player.get_item_production_statistics(s)
  local okR, v = pcall(st.get_flow_count, { name = c.item, category = c.kind == "used" and "output" or "input",
    precision_index = defines.flow_precision_index.one_minute, count = true })
  v = okR and math.floor(v + 0.5) or 0
  return v >= (c.min or 1), v
end

function orders.check(req)
  local s = surface_of(req)
  local area = req.zone and area_of(req) or nil
  local results, all = {}, true
  local impossible
  for _, cond in ipairs(req.conds or {}) do
    local kind, spec = next(cond)
    local fn = CHECKS[kind]
    local okC, pass, value
    if not fn then
      okC, pass, value = true, false, "unknown check " .. tostring(kind)
    elseif kind ~= "rate" and not area and not (type(spec) == "table" and spec.scope == "base") then
      okC, pass, value = true, false, "needs a zone"
    else
      local why
      okC, pass, value, why = pcall(fn, s, area, type(spec) == "table" and spec or {})
      if not okC then pass, value = false, tostring(pass) end
      impossible = why
    end
    all = all and pass
    results[#results + 1] = { check = kind, ok = pass, value = value, impossible = impossible }
    impossible = nil
  end
  return { passed = all, results = results }
end

return orders
