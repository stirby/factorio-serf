-- Todo List's real GUI code against stand-in GUI elements, for what a headless server can't run: a status update
-- from another mod must not wipe what a player is typing into a new-subtask field (review on the remote interface
-- PR, stirby/factorio-todo-list#1), and a player's own save still empties the field.
--
--     lua5.4 tests/todo_gui_mock.lua ~/dev/factorio-todo-list/src
local SRC = arg[1] or (os.getenv("HOME") .. "/dev/factorio-todo-list/src")
package.path = SRC .. "/?.lua;" .. package.path

local FAILS = 0
local function check(name, cond, info)
  print((cond and "ok   " or "FAIL ") .. name .. ((not cond and info) and ("  (" .. tostring(info) .. ")") or ""))
  if not cond then FAILS = FAILS + 1 end
end

-- stand-in GUI elements: any property, children by name, dot-called methods ----------------------------------
local Element = {}
local created = 0
local function new_element(spec, parent)
  created = created + 1
  local e = { _named = {}, children = {}, parent = parent, valid = true, style = {}, text = "", serial = created }
  for k, v in pairs(spec or {}) do
    if k == "style" then e.style = { name = v } else e[k] = v end  -- a style by name: a style object with that name
  end
  return setmetatable(e, Element)
end
local METHODS = {}
function METHODS.add(e, spec)
  local c = new_element(spec, e)
  table.insert(e.children, c)
  if spec.name then e._named[spec.name] = c end
  return c
end
function METHODS.clear(e) for _, c in ipairs(e.children) do c.valid = false end e.children, e._named = {}, {} end
function METHODS.destroy(e)
  e.valid = false
  local p = e.parent
  if p then
    for i, c in ipairs(p.children) do if c == e then table.remove(p.children, i) break end end
    if e.name and p._named[e.name] == e then p._named[e.name] = nil end
  end
end
function METHODS.focus(e) e.focused = true end
function METHODS.force_auto_center() end
function METHODS.bring_to_front() end
function METHODS.scroll_to_element() end
Element.__index = function(e, k)
  if METHODS[k] then return function(a, b) if a == e then return METHODS[k](e, b) end return METHODS[k](e, a) end end
  local named = rawget(e, "_named")
  return named and named[k] or nil
end

-- the game ----------------------------------------------------------------------------------------------------
local function root() return new_element({ type = "flow", name = "" }, nil) end
local player = { index = 1, name = "otterplex", valid = true, connected = true, admin = true,
  gui = { screen = root(), left = root(), top = root(), center = root() } }
function player.print() end
function player.set_shortcut_toggled() end
function player.is_shortcut_toggled() return false end

game = { tick = 1, players = { player }, connected_players = { player } }
function game.get_player(i) return i == 1 and player or nil end
storage = {}
local raised = 0
local next_event = 1000
script = { generate_event_name = function() next_event = next_event + 1 return next_event end,
  raise_event = function() raised = raised + 1 end, on_event = function() end, on_init = function() end,
  on_configuration_changed = function() end }
remote = { interfaces = {}, add_interface = function(name, fns) remote.interfaces[name] = fns end }
function remote.call(name, fn, ...) return remote.interfaces[name][fn](...) end
serpent = { line = function(x) return tostring(x) end, block = function(x) return tostring(x) end,
  dump = function(x) return tostring(x) end }
mod_gui = { get_frame_flow = function(p) return p.gui.left end, get_button_flow = function(p) return p.gui.top end,
  button_style = "button", frame_style = "frame" }
local SETTINGS = { ["todolist-show-log"] = false, ["todolist-show-button"] = true, ["todolist-auto-assign"] = false,
  ["todolist-window-height"] = 600, ["todolist-click-edit-task"] = false }
settings = { get_player_settings = function()
  return setmetatable({}, { __index = function(_, k) return { value = SETTINGS[k] } end })
end, startup = {}, global = {} }
defines = setmetatable({}, { __index = function(t, k)
  local sub = setmetatable({}, { __index = function(_, j) return j end })
  rawset(t, k, sub)
  return sub
end })

require("todo/todo")
todo.mod_init()
storage.todo.settings[player.name] = { expanded_tasks = {} }

local call = function(fn, ...) return remote.call("Todo-List", fn, ...) end
local a = call("add_task", { title = "Roboport grid", task = "as ghosts", assignee = "Robot crew" })
local b = call("add_task", { title = "Fulgora scrap", assignee = "otterplex" })
storage.todo.settings[player.name].expanded_tasks[a] = true
storage.todo.settings[player.name].expanded_tasks[b] = true
todo.maximize_main_frame(player)
todo.refresh_task_table(player)

local function task_table() return todo.get_task_table(player) end
local function field(id) return task_table()["todo_main_subtask_new_text_" .. id] end
check("setup: the list is open with a new-subtask field for each expanded task", field(a) and field(b), "no fields")

-- the reported case: a player is typing a subtask; another mod reports progress on a different task
field(b).text = "half-typed subtask"
local before = field(b)
local ok1 = call("update_task", a, { status = "step 1 of 3", status_kind = "progress" })
check("first status on a task (a redraw): the player's draft survives", ok1 and field(b).text == "half-typed subtask",
  field(b) and field(b).text)

local serial = field(b).serial
local label_flow = task_table()["todo_main_task_status_flow_" .. a]
local ok2 = call("update_task", a, { status = "step 2 of 3", status_kind = "progress" })
local label = label_flow and label_flow["todo_main_task_status_" .. a]
check("a later status change is written in place: same field (focus kept), draft kept, label updated",
  ok2 and field(b).serial == serial and field(b).text == "half-typed subtask" and label and label.valid
  and string.find(tostring(label.caption), "step 2 of 3", 1, true) ~= nil,
  tostring(field(b).serial == serial) .. " " .. tostring(label and label.caption))
check("the in-place update still tells other mods the list changed", raised >= 3, raised)

call("set_subtasks", a, "robot-crew", { { task = "gather", done = true }, { task = "build", done = false } })
check("set_subtasks (a redraw) keeps the draft", field(b).text == "half-typed subtask", field(b).text)
call("add_task", { title = "Third", assignee = "Robot crew" })
call("mark_complete", a)
check("add_task and mark_complete (redraws) keep the draft", field(b).text == "half-typed subtask", field(b).text)
_ = before

-- a player's own save still empties the field (the redraw after it isn't the interface's)
todo.on_save_new_subtask_click(player, b)
check("the player saving their subtask empties the field and adds it", field(b) and field(b).text == ""
  and #todo.get_task_by_id(b).subtasks.open == 1, field(b) and field(b).text)

-- status text cut at a character boundary
call("update_task", b, { status = string.rep("界", 67) })
local s = todo.get_task_by_id(b).status
check("a 201-byte status is cut to whole characters (66 of them, 198 bytes)", #s == 198 and utf8.len(s) == 66,
  #s .. " " .. tostring(utf8.len(s)))

print(FAILS == 0 and "\nALL OK" or ("\n" .. FAILS .. " FAILED"))
os.exit(FAILS == 0 and 0 or 1)
