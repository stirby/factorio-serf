-- What each agent is doing right now, for every player: a top-left panel (state, task, latest thought) and a
-- short state line over the agent's head. The orchestrator pushes state (API.status); jobs come from the queue.
-- "idle" only shows when the model is out of usage: otherwise an agent is thinking or doing something.
local agents = require("scripts.agents")
local jobs = require("scripts.jobs")
local link = require("scripts.link")

local panel = {}
local NAME = "factorio_serf_panel"
local TASKS = "factorio_serf_tasks"

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

-- Only an agent that's here and has its app connected gets a card, a state over its head and the Teach shortcut:
-- with none, the mod shows nothing.
local function shown(a)
  return not a.away and link.online(link.client_of(a)) and a.state ~= "offline"
end

function panel.refresh()
  panel.refresh_tasks()
  storage.panel_hidden = storage.panel_hidden or {}
  local brand = storage.brand or { title = "Serfs" }
  local names = {}
  for name in pairs(storage.agents) do names[#names + 1] = name end
  table.sort(names)
  local cards = {}
  for _, name in ipairs(names) do
    local a = storage.agents[name]
    if not shown(a) then
      if a.state_tag and a.state_tag.valid then a.state_tag.destroy() end
      a.state_tag = nil
    else
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
  end
  for _, p in pairs(game.connected_players) do
    local ok, err = pcall(panel.draw_left, p, cards, brand)
    if not ok then panel.gui_error(p, err) end
  end
end

function panel.draw_left(p, cards, brand)
  do
    local on = #cards > 0
    if p.is_shortcut_available("factorio-serf-teach") ~= on then p.set_shortcut_available("factorio-serf-teach", on) end
    local f = p.gui.left[NAME]
    if #cards == 0 or storage.panel_hidden[p.index] then
      if f then f.destroy() end
    else
      if f and not f.body then f.destroy() f = nil end  -- a panel from before the Tasks button
      if not f then
        f = p.gui.left.add { type = "frame", name = NAME, caption = brand.title, direction = "vertical" }
        f.style.maximal_width = 440
        f.add { type = "flow", name = "body", direction = "vertical" }
        f.add { type = "button", name = TASKS .. "_open", caption = "Tasks (Ctrl+Shift+J)",
          tooltip = "What your serf is doing: its plan's steps and its queue" }
      end
      f.caption = brand.title
      local body = f.body
      body.clear()
      for i, lines in ipairs(cards) do
        if i > 1 then body.add { type = "line" } end
        for _, l in ipairs(lines) do
          local lbl = body.add { type = "label", caption = l }
          lbl.style.single_line = false
          lbl.style.maximal_width = 420
        end
      end
    end
  end
end

-- Serf tasks: a window (open it with Ctrl+Shift+J, the panel's Tasks button or /serf tasks) with each serf's order and
-- the steps of its plan (done, now, failed, to do), its queue and what finished lately. The serf's app sends this
-- (API.board); the window is rebuilt when that changes, and every 5 s for the clock. Live test: "It's unclear to me
-- the queue of actions that the agent is taking, I want to see the full list".
local MARK = { ok = { "done", { 0.5, 0.95, 0.5 } }, run = { "now", { 1, 0.85, 0.3 } }, fail = { "failed", { 1, 0.4, 0.35 } },
  todo = { "", { 0.7, 0.7, 0.7 } } }

local function mins(secs)
  secs = math.max(0, math.floor(secs))
  if secs < 60 then return secs .. "s" end
  return math.floor(secs / 60) .. "m " .. (secs % 60) .. "s"
end

local function add_line(parent, text, font)
  local l = parent.add { type = "label", caption = font and ("[font=" .. font .. "]" .. text .. "[/font]") or text }
  l.style.single_line = false
  l.style.maximal_width = 460
  return l
end

local function fill_tasks(box)
  box.clear()
  local names = {}
  for name in pairs(storage.agents) do names[#names + 1] = name end
  table.sort(names)
  local any = false
  for _, name in ipairs(names) do
    local a = storage.agents[name]
    if shown(a) then
      any = true
      local b = a.board or {}
      local long, _, c = state_of(a)
      add_line(box, color(a.color, "[font=default-bold]" .. name .. "[/font]") .. "  " .. color(c, long))
      local now = b.now
      if now then
        local secs = (now.secs or 0) + (game.tick - (a.board_tick or game.tick)) / 60
        add_line(box, "[font=default-bold]Now:[/font] #" .. tostring(now.id) .. " " .. tostring(now.text or "")
          .. color(C.dim, "  (" .. tostring(now.status or "") .. ", " .. mins(secs) .. ")"))
      else
        add_line(box, color(C.dim, "No order running."))
      end
      local plan = b.plan
      if now and plan and plan.order == now.id then
        if plan.goal and plan.goal ~= "" then add_line(box, "[font=default-bold]Plan:[/font] " .. tostring(plan.goal)) end
        for i, st in ipairs(plan.steps or {}) do
          local m = MARK[st.state or "todo"] or MARK.todo
          local tag = m[1] ~= "" and (color(m[2], "[" .. m[1] .. "]") .. " ") or ""
          add_line(box, "   " .. i .. ". " .. tag .. color(st.state == "todo" and C.dim or { 1, 1, 1 }, tostring(st.text or "")),
            "default-small")
        end
      elseif now and b.thinking then
        add_line(box, color(C.thinking, "Planning it..."))
      end
      local q = b.queue or {}
      add_line(box, "[font=default-bold]Queue:[/font] " .. (#q == 0 and color(C.dim, "empty") or ""))
      for _, o in ipairs(q) do
        add_line(box, "   #" .. tostring(o.id) .. " " .. tostring(o.text or "") .. color(C.dim, "  (" .. tostring(o.by or "")
          .. ((o.notes or 0) > 0 and (", +" .. o.notes .. " notes") or "") .. ")"), "default-small")
      end
      local r = b.recent or {}
      if #r > 0 then
        add_line(box, "[font=default-bold]Recent:[/font]")
        for _, o in ipairs(r) do
          local col = o.status == "done" and MARK.ok[2] or (o.status == "failed" and MARK.fail[2] or C.dim)
          add_line(box, "   #" .. tostring(o.id) .. " " .. color(col, tostring(o.status or "")) .. "  " .. tostring(o.text or ""),
            "default-small")
        end
      end
      box.add { type = "line" }
    end
  end
  if not any then add_line(box, color(C.dim, "No serf is connected.")) end
end

local function open_tasks(p)
  local f = p.gui.screen[TASKS]
  if f then return f end
  f = p.gui.screen.add { type = "frame", name = TASKS, direction = "vertical" }
  f.style.maximal_width = 500
  local bar = f.add { type = "flow", direction = "horizontal" }
  local title = bar.add { type = "label", caption = "[font=default-bold]Serf tasks[/font]" }
  title.drag_target = f
  local pad = bar.add { type = "label", caption = "" }  -- pushes the button right, and drags the window too
  pad.style.horizontally_stretchable = true
  pad.drag_target = f
  bar.add { type = "button", name = TASKS .. "_close", caption = "Close", tooltip = "Ctrl+Shift+J opens it again" }
  local sp = f.add { type = "scroll-pane", name = "scroll" }
  sp.style.maximal_height = 560
  sp.add { type = "flow", name = "box", direction = "vertical" }
  f.auto_center = true
  return f
end

function panel.refresh_tasks(force)
  storage.tasks_open = storage.tasks_open or {}
  local newest = 0
  for _, a in pairs(storage.agents) do newest = math.max(newest, a.board_tick or 0) end
  for idx in pairs(storage.tasks_open) do
    local p = game.get_player(idx)
    local f = p and p.connected and p.gui.screen[TASKS]
    if not f then
      storage.tasks_open[idx] = nil
    elseif force or (storage.tasks_drawn or {})[idx] ~= newest or game.tick % 300 == 0 then
      local ok, err = pcall(fill_tasks, f.scroll.box)
      if not ok then panel.gui_error(p, err) end
      storage.tasks_drawn = storage.tasks_drawn or {}
      storage.tasks_drawn[idx] = newest
    end
  end
end

function panel.toggle_tasks(player)
  storage.tasks_open = storage.tasks_open or {}
  local f = player.gui.screen[TASKS]
  if f then
    f.destroy()
    storage.tasks_open[player.index] = nil
    return
  end
  local ok, err = pcall(open_tasks, player)
  if not ok then return panel.gui_error(player, err) end
  storage.tasks_open[player.index] = true
  panel.refresh_tasks(true)
end

-- A GUI mistake (this code can't run on the headless test servers) shows once in chat instead of stopping the game.
function panel.gui_error(player, err)
  storage.gui_errors = storage.gui_errors or {}
  local key = tostring(err):sub(1, 200)
  if storage.gui_errors[key] then return end
  storage.gui_errors[key] = true
  if player and player.valid then player.print("[serf] window error (tell the developer): " .. key, { color = { 1, 0.4, 0.3 } }) end
end

function panel.on_click(e)
  local el = e.element
  if not (el and el.valid) then return end
  local p = game.get_player(e.player_index)
  if el.name == TASKS .. "_close" or el.name == TASKS .. "_open" then panel.toggle_tasks(p) end
end

function panel.toggle(player)
  storage.panel_hidden = storage.panel_hidden or {}
  storage.panel_hidden[player.index] = not storage.panel_hidden[player.index]
  panel.refresh()
end

return panel
