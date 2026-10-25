-- Off-game smoke test of the serf mod's GUI (scripts/panel.lua: the left panel strip and the Serf tasks window).
-- GUI code can't run on the headless test servers (no players), so this runs it in plain Lua against stand-in GUI
-- elements that enforce the rules most likely to break in game: known element types, style properties that only
-- some elements have, drag targets, progressbar values. Any error, or a "window error" the panel prints, fails.
--
--     lua5.4 tests/gui_smoke.lua        (from the repo root)
package.path = "mod/factorio-serf/?.lua;" .. package.path

local FAILS = 0
local function check(name, cond, info)
  print((cond and "ok   " or "FAIL ") .. name .. ((not cond and info) and ("  (" .. tostring(info) .. ")") or ""))
  if not cond then FAILS = FAILS + 1 end
end

-- stand-in GUI elements -------------------------------------------------------------------------------------------
local TYPES = { frame = true, flow = true, label = true, button = true, ["sprite-button"] = true, line = true,
  ["scroll-pane"] = true, progressbar = true, ["empty-widget"] = true, textfield = true, table = true,
  checkbox = true, ["drop-down"] = true }
local STYLE_ONLY = {  -- style property -> element types that have it (Factorio errors on the others)
  horizontal_spacing = { flow = true, table = true }, vertical_spacing = { flow = true, table = true },
  single_line = { label = true },
}
local DRAG_FROM = { flow = true, label = true, frame = true, ["empty-widget"] = true }

local function new_style(kind)
  return setmetatable({}, { __newindex = function(t, k, v)
    local only = STYLE_ONLY[k]
    if only and not only[kind] then error("style." .. k .. " doesn't exist on a " .. kind, 2) end
    rawset(t, k, v)
  end })
end

local Element = {}
local function new_element(spec, parent, root)
  if not TYPES[spec.type] then error("unknown element type " .. tostring(spec.type), 3) end
  if spec.type == "progressbar" and spec.value and (spec.value < 0 or spec.value > 1) then
    error("progressbar value out of range: " .. spec.value, 3)
  end
  local e = { type = spec.type, name = spec.name, caption = spec.caption, value = spec.value, tooltip = spec.tooltip,
    valid = true, children = {}, parent = parent, root = root, _named = {} }
  e.style = new_style(spec.type)
  return setmetatable(e, Element)
end
Element.__index = function(e, k)
  -- methods are called with a dot in Factorio (e.add{...}, e.destroy()); a colon works too
  if Element[k] then return function(a, b) if a == e then return Element[k](e, b) end return Element[k](e, a) end end
  local named = rawget(e, "_named")
  if named and named[k] then return named[k] end
  return nil
end
Element.__newindex = function(e, k, v)
  if k == "drag_target" then
    if not DRAG_FROM[e.type] then error("drag_target can't be set on a " .. e.type, 2) end
    if not (v and v.parent and v.parent.is_screen) then error("drag_target must be a top-level screen element", 2) end
  elseif k == "auto_center" then
    if not (e.parent and e.parent.is_screen) then error("auto_center only on a screen element", 2) end
  end
  rawset(e, k, v)
end
function Element.add(e, spec)
  if not e.valid then error("add on an invalid element", 2) end
  if spec.name and e._named[spec.name] then error("duplicate child name " .. spec.name, 2) end
  local c = new_element(spec, e, e.root or e)
  table.insert(e.children, c)
  if spec.name then e._named[spec.name] = c end
  return c
end
function Element.clear(e)
  for _, c in ipairs(e.children) do c.valid = false end
  e.children, e._named = {}, {}
end
function Element.destroy(e)
  e.valid = false
  local p = e.parent
  if p then
    for i, c in ipairs(p.children) do if c == e then table.remove(p.children, i) break end end
    if e.name then p._named[e.name] = nil end
  end
end
local function root(is_screen)
  local r = setmetatable({ type = "flow", valid = true, children = {}, _named = {}, is_screen = is_screen,
    style = new_style("flow") }, Element)
  return r
end

-- the game, as panel.lua uses it ----------------------------------------------------------------------------------
local printed = {}
local player = { index = 1, name = "otterplex", valid = true, connected = true,
  gui = { left = root(false), screen = root(true) }, shortcuts = {} }
function player.print(msg) printed[#printed + 1] = tostring(msg) end
function player.is_shortcut_available(name) return player.shortcuts[name] or false end
function player.set_shortcut_available(name, on) player.shortcuts[name] = on end

game = { tick = 0, connected_players = { player }, players = { player } }
function game.get_player(i) return i == 1 and player or nil end
storage = { agents = {} }
rendering = { draw_text = function(t) return { valid = true, text = t.text, color = t.color, destroy = function() end } end }

package.preload["scripts.agents"] = function() return { alive = function(a) return a.char ~= nil end } end
package.preload["scripts.jobs"] = function()
  return { describe = function(job) if not job then return nil end return { op = job.op, walking_to = job.to } end }
end
package.preload["scripts.link"] = function()
  return { online = function() return true end, client_of = function() return "rcon" end }
end

local panel = require("scripts.panel")

local function serf(board, extra)
  local a = { name = "serf", color = { r = 0.94, g = 0.55, b = 0.24 }, char = { surface = "vulcanus", valid = true },
    state = "working", state_since = 0, board = board, board_tick = 0, queue = {} }
  for k, v in pairs(extra or {}) do a[k] = v end
  return a
end

local FULL = {
  thinking = false,
  now = { id = 4, text = '"make a clean grid of robot ports as ghosts"', status = "working", secs = 192 },
  plan = { order = 4, goal = "roboports ~48 apart", steps = {
    { text = "fetch 10 roboport", state = "ok" }, { text = "lay out 6 buildings", state = "ok" },
    { text = "power 23,-140", state = "run" }, { text = "build ghosts", state = "todo" } } },
  queue = { { id = 5, text = "dump stone in lava", by = "otterplex", notes = 1 } },
  recent = { { id = 3, text = "boulders", status = "failed" }, { id = 2, text = "rocks", status = "done" } },
}
local BOARDS = {
  { "a full board", FULL },
  { "no board yet", nil },
  { "an empty board", { queue = {}, recent = {} } },
  { "planning, no plan yet", { thinking = true, now = { id = 7, text = '"x"', status = "thinking", secs = 3 }, queue = {}, recent = {} } },
  { "needs the player", { now = { id = 8, text = '"y"', status = "working", secs = 9, needs = "ping where you want it" },
    plan = { order = 8, goal = "", steps = { { text = "a", state = "fail" } } }, queue = {}, recent = {} } },
  { "a plan for another order", { now = { id = 9, text = '"z"', status = "working", secs = 1 },
    plan = { order = 2, goal = "old", steps = { { text = "a", state = "ok" } } }, queue = {}, recent = {} } },
  { "odd states and missing text", { now = { id = 10, status = "working" },
    plan = { order = 10, steps = { { state = "weird" }, {} } }, queue = { {} }, recent = { {} } } },
}

local function run(name, fn)
  printed = {}
  local ok, err = pcall(fn)
  local werr = nil
  for _, p in ipairs(printed) do if p:find("window error") then werr = p end end
  check(name, ok and not werr, err or werr)
end

for _, case in ipairs(BOARDS) do
  storage.agents = { serf = serf(case[2]) }
  game.tick = game.tick + 30
  run("panel strip: " .. case[1], function() panel.refresh() end)
  run("tasks window opens: " .. case[1], function()
    if player.gui.screen.factorio_serf_tasks then panel.toggle_tasks(player) end
    panel.toggle_tasks(player)
    assert(player.gui.screen.factorio_serf_tasks, "no window")
    game.tick = game.tick + 30
    panel.refresh()
  end)
end

storage.agents = { serf = serf(FULL) }
run("panel: the Tasks button and the window's Close button toggle it", function()
  panel.refresh()
  local f = player.gui.left.factorio_serf_panel
  assert(f and f.factorio_serf_tasks_open, "no Tasks button on the panel")
  if player.gui.screen.factorio_serf_tasks then panel.toggle_tasks(player) end
  panel.on_click({ element = f.factorio_serf_tasks_open, player_index = 1 })
  local w = player.gui.screen.factorio_serf_tasks
  assert(w, "the Tasks button didn't open the window")
  local close
  local function find(e) for _, c in ipairs(e.children) do if c.name == "factorio_serf_tasks_close" then close = c end find(c) end end
  find(w)
  assert(close, "no Close button")
  panel.on_click({ element = close, player_index = 1 })
  assert(not player.gui.screen.factorio_serf_tasks, "Close didn't close it")
end)
run("panel: a panel from before the Tasks button is replaced", function()
  if player.gui.left.factorio_serf_panel then player.gui.left.factorio_serf_panel.destroy() end
  player.gui.left:add { type = "frame", name = "factorio_serf_panel" }  -- the old shape: no body flow
  panel.refresh()
  assert(player.gui.left.factorio_serf_panel.body, "old panel not rebuilt")
end)
storage.agents = { serf = serf(FULL, { away = true }) }
run("panel: an away serf shows nothing", function()
  panel.refresh()
  assert(not player.gui.left.factorio_serf_panel, "panel still shown")
end)

print(FAILS == 0 and "\nALL OK" or ("\n" .. FAILS .. " FAILED"))
os.exit(FAILS == 0 and 0 or 1)
