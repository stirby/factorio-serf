-- x-sweep setup: 12 small smelter sites spread over ~300x300 tiles. Each: an infinity ore chest, a fast inserter
-- onto a short belt, 2-4 stone furnaces fed by inserters off it, an output chest per furnace, and its own grid
-- corner (energy interface + poles). 7 sites are stopped: no fuel (2), output chests full of stone (2), the ore belt
-- cut after the first furnace (2), one furnace's input inserter gone (1). Met = all 12 sites smelting.
local CX, CY
if LAB then CX, CY = find_near(-8, -8, 16, 16, 40) else CX, CY = find_ring(16, 16, 230, 260) end
local KIND = { "ok", "fuel", "ok", "full", "cut", "ok", "noins", "fuel", "cut", "ok", "full", "ok" }
local sites = {}
local k = 0
for row = -1, 1 do
  for col = -1.5, 1.5 do
    k = k + 1
    local n = 2 + (k % 3)
    local w = 2 * n + 3
    local ox, oy = find_near(CX + col * 90 + (k * 7) % 13, CY + row * 110 + (k * 11) % 17, 12, 8, 60)
    clear(ox, oy, 12, 8)
    local X, Y = ox + 1, oy
    local function at(name, x, y, dir) return put(name, X + x, Y + y, dir) end
    grid(X, Y + 3, 1000000)
    at("medium-electric-pole", 1.5, 2.5)
    if n >= 3 then at("medium-electric-pole", 7.5, 1.5) end
    source(X + 0.5, Y + 0.5, { "iron-ore" })
    at("fast-inserter", 1.5, 0.5, D.west)
    for x = 2, 2 * n do at("transport-belt", x + 0.5, 0.5, D.east) end
    local kind = KIND[k]
    for i = 1, n do
      local x = 1 + 2 * i
      local fu = at("stone-furnace", x, 3)
      if kind ~= "fuel" then fu.insert { name = "coal", count = 50 } end
      if not (kind == "noins" and i == n) then at("inserter", x - 0.5, 1.5, D.north) end
      at("inserter", x - 0.5, 4.5, D.north)
      local c = at("wooden-chest", x - 0.5, 5.5)
      if kind == "full" then
        c.insert { name = "stone", count = 800 }
        fu.get_output_inventory().insert { name = "iron-plate", count = 100 }
      end
    end
    if kind == "cut" then s.find_entity("transport-belt", { X + 3.5, Y + 0.5 }).destroy() end
    sites[k] = { box = { { X - 1, Y }, { X + w - 1, Y + 7 } }, kind = kind, X = X, Y = Y, n = n }
  end
end
storage.bench_sweep = { sites = sites }
return { center = gps(CX + 8, CY + 8) }
