-- World annotations, modeled on logistic chests: the lead (or anyone) marks a spot as a provider (shared
-- surplus, take freely), requester (deliver these items here), storage (overflow) or a plain note.
-- Each mark shows as a map tag and a floating label for humans too, and reports live chest contents.
local util = require("scripts.util")

local marks = {}

local ICON = { provider = "iron-chest", requester = "iron-chest", storage = "wooden-chest", note = "small-lamp" }
local COLOR = {
  provider = { 0.9, 0.3, 0.3 }, requester = { 0.3, 0.6, 1 }, storage = { 0.9, 0.8, 0.3 }, note = { 0.8, 0.8, 0.8 },
}

local function chest_at(surface, pos)
  local list = surface.find_entities_filtered { position = pos, radius = 1.2, type = { "container", "logistic-container" } }
  return list[1]
end

function marks.add(surface, by, args)
  storage.marks = storage.marks or {}
  storage.next_mark = (storage.next_mark or 0) + 1
  local kind = args.kind or "note"
  if not ICON[kind] then error("kind must be provider, requester, storage or note") end
  local pos = util.pos(args.position or { args.x, args.y })
  if not (pos and pos.x) then error("mark needs x,y") end
  local text = tostring(args.text or kind)
  local id = storage.next_mark
  local m = { id = id, kind = kind, position = pos, text = text, by = by, requests = args.requests,
    surface = surface.name }
  local label = "[" .. kind .. "] " .. text
  local okT, tag = pcall(function()
    return game.forces.player.add_chart_tag(surface, { position = pos, text = label,
      icon = { type = "item", name = ICON[kind] } })
  end)
  if okT then m.tag = tag end
  m.label = rendering.draw_text { text = label, surface = surface, target = { pos.x, pos.y - 1.2 },
    color = COLOR[kind], scale = 1.0, alignment = "center", vertical_alignment = "middle" }
  storage.marks[id] = m
  return m
end

function marks.remove(id)
  local m = storage.marks and storage.marks[id]
  if not m then error("no mark " .. tostring(id)) end
  if m.tag and m.tag.valid then m.tag.destroy() end
  if m.label and m.label.valid then m.label.destroy() end
  storage.marks[id] = nil
end

-- Marks with live contents; requesters also report what's still missing.
function marks.list()
  local out = {}
  for id, m in pairs(storage.marks or {}) do
    local d = { id = id, kind = m.kind, p = util.xy(m.position), text = m.text, by = m.by }
    local surface = game.surfaces[m.surface or "nauvis"]
    local chest = surface and chest_at(surface, m.position)
    if chest then
      d.contents = util.contents(chest.get_inventory(defines.inventory.chest))
      if m.requests then
        local missing = {}
        for item, want in pairs(m.requests) do
          local have = d.contents[item] or 0
          if have < want then missing[item] = want - have end
        end
        d.requests, d.missing = m.requests, next(missing) and missing or nil
      end
    elseif m.kind ~= "note" then
      d.warning = "no chest here yet"
    end
    out[#out + 1] = d
  end
  table.sort(out, function(x, y) return x.id < y.id end)
  return out
end

return marks
