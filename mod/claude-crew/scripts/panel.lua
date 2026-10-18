-- Small top-left panel for every player: one line per agent with its status text and current job.
local agents = require("scripts.agents")
local jobs = require("scripts.jobs")
local util = require("scripts.util")

local panel = {}
local NAME = "claude_crew_panel"

local function color_tag(c, s)
  return string.format("[color=%.2f,%.2f,%.2f]%s[/color]", c.r, c.g, c.b, s)
end

function panel.refresh()
  storage.panel_hidden = storage.panel_hidden or {}
  local lines = {}
  local names = {}
  for name in pairs(storage.agents) do names[#names + 1] = name end
  table.sort(names)
  for _, name in ipairs(names) do
    local a = storage.agents[name]
    local job = a.job and jobs.describe(a.job)
    local doing = job and (job.op .. (job.walking_to and " (walking)" or "")) or "idle"
    if not agents.alive(a) then doing = "dead, respawning" end
    lines[#lines + 1] = color_tag(a.color, name) .. "  [font=default-small]" .. doing .. "[/font]"
    if a.status_text and a.status_text ~= "" then
      lines[#lines + 1] = "   [font=default-small][color=0.8,0.8,0.8]" .. a.status_text .. "[/color][/font]"
    end
  end
  for _, p in pairs(game.connected_players) do
    local f = p.gui.left[NAME]
    if #lines == 0 or storage.panel_hidden[p.index] then
      if f then f.destroy() end
    else
      if not f then
        f = p.gui.left.add { type = "frame", name = NAME, caption = "Claude Crew", direction = "vertical" }
        f.style.maximal_width = 420
      end
      f.clear()
      for _, l in ipairs(lines) do
        local lbl = f.add { type = "label", caption = l }
        lbl.style.single_line = false
        lbl.style.maximal_width = 400
      end
    end
  end
end

function panel.toggle(player)
  storage.panel_hidden = storage.panel_hidden or {}
  storage.panel_hidden[player.index] = not storage.panel_hidden[player.index]
  panel.refresh()
end

return panel
