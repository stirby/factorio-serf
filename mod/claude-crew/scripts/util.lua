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
  local s = settings.global["claude-crew-cheat"]
  return s and s.value or false
end

-- Player-like name lookups.
function util.find_player(name)
  for _, p in pairs(game.players) do
    if p.name == name then return p end
  end
end

return util
