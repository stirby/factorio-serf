-- What each agent is doing right now, for every player: a top-left panel (state, task, latest thought) and a
-- short state line over the agent's head. The orchestrator pushes state (API.status); jobs come from the queue.
-- "idle" only shows when the model is out of usage: otherwise an agent is thinking or doing something.
local agents = require("scripts.agents")
local jobs = require("scripts.jobs")
local link = require("scripts.link")

local panel = {}
local NAME = "claude_crew_panel"

local C = {
  thinking = { 0.55, 0.75, 1 }, doing = { 0.5, 0.95, 0.5 }, warn = { 1, 0.65, 0.2 }, bad = { 1, 0.35, 0.3 },
  dim = { 0.7, 0.7, 0.7 }, thought = { 0.85, 0.85, 0.75 },
}

local VERB = {
  move = "walking", mine = "mining", craft = "crafting", place = "building", insert = "loading", take = "fetching",
  set_recipe = "setting a recipe", rotate = "rotating", research = "queuing research", wait = "waiting on a job",
  connect = "laying a line", follow = "following", come = "coming", fuel = "refueling", build_ghosts = "building",
  configure = "configuring", limit = "setting a limit", equip = "suiting up", pickup = "picking up",
}

local function hex(c) return string.format("%.2f,%.2f,%.2f", c[1] or c.r, c[2] or c.g, c[3] or c.b) end
local function color(c, s) return "[color=" .. hex(c) .. "]" .. s .. "[/color]" end

local function doing_words(a)
  local job = a.job and jobs.describe(a.job)
  if not job then return nil end
  local w = VERB[job.op] or job.op:gsub("_", " ")
  if job.walking_to then w = w .. " to " .. math.floor(job.walking_to[1]) .. "," .. math.floor(job.walking_to[2]) end
  local q = #(a.queue or {})
  if q > 0 then w = w .. " (+" .. q .. " queued)" end
  return w
end

-- Returns long text (panel), short text (over the head), color.
local function state_of(a)
  if not agents.alive(a) then return "dead, respawning", "respawning", C.bad end
  if not link.online(link.client_of(a)) or a.state == "offline" then
    return "offline: " .. (a.owner and (a.owner .. "'s serf app") or "the orchestrator") .. " isn't running", "offline", C.dim
  end
  local doing = doing_words(a)
  local secs = math.floor((game.tick - (a.state_since or game.tick)) / 60)
  local st, detail = a.state, a.state_detail or ""
  if st == "limit" then
    return "idle: out of Claude usage" .. (detail ~= "" and (" (" .. detail .. ")") or ""), "out of usage", C.bad
  elseif st == "paused" then
    return "paused: " .. detail, "paused", C.warn
  elseif st == "error" then
    return "retrying: " .. detail, "retrying", C.warn
  elseif st == "thinking" then
    local dots = string.rep(".", 1 + math.floor(game.tick / 30) % 3)
    local t = "thinking" .. dots .. " " .. secs .. "s"
    if doing then return doing .. "  +  " .. t, (doing:gsub(" %(.*", "")), C.doing end
    return t, "thinking" .. dots, C.thinking
  end
  if doing then return doing, doing:gsub(" %(.*", ""), C.doing end
  if st == "waiting" then
    return "waiting for orders" .. (a.owner and (" from " .. a.owner) or ""), "ready for orders", C.dim
  end
  return "deciding what's next", "...", C.thinking
end

local function update_overhead(a, short, c)
  if not agents.alive(a) then return end
  if not (a.state_tag and a.state_tag.valid) then
    a.state_tag = rendering.draw_text {
      text = short, surface = a.char.surface, target = { entity = a.char, offset = { 0, -3.15 } },
      color = c, scale = 0.85, alignment = "center", vertical_alignment = "middle", use_rich_text = false,
    }
  elseif a.state_tag.text ~= short then
    a.state_tag.text = short
    a.state_tag.color = c
  end
end

function panel.refresh()
  storage.panel_hidden = storage.panel_hidden or {}
  local brand = storage.brand or { title = "Serfs" }
  local names = {}
  for name in pairs(storage.agents) do names[#names + 1] = name end
  table.sort(names)
  local cards = {}
  for _, name in ipairs(names) do
    local a = storage.agents[name]
    local long, short, c = state_of(a)
    update_overhead(a, short, c)
    local who = (a.owner and name ~= a.owner) and ("  [font=default-small]" .. color(C.dim, "with " .. a.owner) .. "[/font]") or ""
    local lines = { color(a.color, "[font=default-bold]" .. name .. "[/font]") .. who
      .. (a.model and ("  [font=default-small]" .. color(C.dim, a.model) .. "[/font]") or "") }
    lines[#lines + 1] = color(c, long)
    if a.task_text and a.task_text ~= "" then lines[#lines + 1] = "[font=default-small]task: " .. a.task_text .. "[/font]" end
    if a.thought and a.thought ~= "" then
      lines[#lines + 1] = "[font=default-small]" .. color(C.thought, "\"" .. a.thought .. "\"") .. "[/font]"
    elseif a.status_text and a.status_text ~= "" then
      lines[#lines + 1] = "[font=default-small]" .. color(C.dim, a.status_text) .. "[/font]"
    end
    cards[#cards + 1] = lines
  end
  for _, p in pairs(game.connected_players) do
    local f = p.gui.left[NAME]
    if #cards == 0 or storage.panel_hidden[p.index] then
      if f then f.destroy() end
    else
      if not f then
        f = p.gui.left.add { type = "frame", name = NAME, caption = brand.title, direction = "vertical" }
        f.style.maximal_width = 440
      end
      f.caption = brand.title
      f.clear()
      for i, lines in ipairs(cards) do
        if i > 1 then f.add { type = "line" } end
        for _, l in ipairs(lines) do
          local lbl = f.add { type = "label", caption = l }
          lbl.style.single_line = false
          lbl.style.maximal_width = 420
        end
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
