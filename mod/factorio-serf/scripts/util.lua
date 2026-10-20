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
