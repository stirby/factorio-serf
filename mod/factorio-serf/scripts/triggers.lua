-- Script-driven characters don't count as players, so their hand-crafting, building and mining
-- don't show up in production stats or advance trigger techs. Record them the way a player's would be.
local triggers = {}

local function trigger_item(trig)
  local it = trig.item or trig.entity
  if type(it) == "table" then return it.name end
  return it
end

local function prereqs_done(tech)
  for _, pre in pairs(tech.prerequisites) do
    if not pre.researched then return false end
  end
  return true
end

-- kind: "craft-item" | "build-entity" | "mine-entity"
function triggers.note(force, surface, kind, name, count)
  storage.trigger_counts = storage.trigger_counts or {}
  local key = kind .. ":" .. name
  storage.trigger_counts[key] = (storage.trigger_counts[key] or 0) + count
  if kind == "craft-item" and surface then
    local stats = force.get_item_production_statistics(surface)
    stats.on_flow(name, count)
  end
  for _, tech in pairs(force.technologies) do
    if not tech.researched and tech.enabled then
      local trig = tech.prototype.research_trigger
      if trig and trig.type == kind and trigger_item(trig) == name and prereqs_done(tech)
          and storage.trigger_counts[key] >= (trig.count or 1) then
        tech.researched = true
      end
    end
  end
end

-- After a prerequisite finishes, a trigger may already be satisfied by earlier work.
function triggers.recheck(force)
  for _, tech in pairs(force.technologies) do
    if not tech.researched and tech.enabled then
      local trig = tech.prototype.research_trigger
      if trig and prereqs_done(tech) then
        local key = trig.type .. ":" .. tostring(trigger_item(trig))
        if (storage.trigger_counts or {})[key] and storage.trigger_counts[key] >= (trig.count or 1) then
          tech.researched = true
        end
      end
    end
  end
end

return triggers
