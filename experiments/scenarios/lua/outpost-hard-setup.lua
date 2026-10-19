-- d1b-iron-outpost-hard setup (stage S3): like d1 but no power at the stop and no electric drills in stock.
-- (d1 text follows): an untouched iron patch ~300 tiles SW of the base, a short east-west rail line
-- 35 tiles north of it with a train stop, a parked train (locomotive + cargo wagon), and power at the stop (a hidden
-- electric-energy-interface standing in for the outpost's grid connection). Returns the positions the goal uses.
local s, f = game.surfaces.nauvis, game.forces.player
local ore = s.find_entities_filtered{name="iron-ore", position={-225,170}, radius=40}
local x1,y1,x2,y2 = 1e9,1e9,-1e9,-1e9
for _,r in pairs(ore) do local p=r.position x1=math.min(x1,p.x) y1=math.min(y1,p.y) x2=math.max(x2,p.x) y2=math.max(y2,p.y) end
local px, py = math.floor((x1+x2)/2), math.floor((y1+y2)/2)
for _, e in pairs(s.find_entities_filtered{area={{-262,114},{-188,132}}, type={"tree","simple-entity"}}) do e.destroy() end
for x = -255, -195, 2 do
  s.create_entity{name="straight-rail", position={x,122}, direction=defines.direction.east, force=f}
end
local ry = s.find_entities_filtered{name="straight-rail", position={-225,122}, radius=4}[1].position.y
local stop = s.create_entity{name="train-stop", position={-223, ry + 2}, direction=defines.direction.east, force=f}
stop.backer_name = "Iron Outpost"
local loco = s.create_entity{name="locomotive", position={-227, ry}, direction=defines.direction.east, force=f}
local wagon = s.create_entity{name="cargo-wagon", position={-234, ry}, direction=defines.direction.east, force=f}
local pole = nil
local removed = 0
for _, c in pairs(s.find_entities_filtered{type={"container","logistic-container"}, force=f}) do
  local n = c.get_item_count("electric-mining-drill")
  if n > 0 then removed = removed + c.remove_item{name="electric-mining-drill", count=n} end
end
storage.bench_outpost = {patch={x1,y1,x2,y2}, stop={stop.position.x, stop.position.y}, wagon=wagon.unit_number}
return {px=px, py=py, sx=math.floor(stop.position.x), sy=math.floor(stop.position.y),
  wx=math.floor(wagon.position.x), wy=math.floor(wagon.position.y), stop_rail=stop.connected_rail ~= nil,
  loco=loco ~= nil, wagon_ok=wagon ~= nil, drills_removed=removed}
