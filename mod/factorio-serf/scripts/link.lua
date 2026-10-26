-- Who drives the agents, and how messages reach them. Each orchestrator is a "client":
--   * over RCON (a server operator's `crew up`): names itself in its requests (default "rcon"); trusted.
--   * over localhost UDP (a player's own `serf` app, Factorio started with --enable-lua-udp PORT): "p<player_index>".
--     Works in single player and from any client in multiplayer: the packet becomes an input action, so every
--     peer runs the request the same way and only that player's machine sends the reply. Untrusted: it may only
--     drive the agents it owns.
-- Chat and events go into one feed; every client reads it from its own cursor, so two orchestrators never steal
-- each other's messages. Job results stay with the agent and go to the client that owns the agent.
local link = {}

local FEED_KEEP = 600
local ONLINE_TICKS = 60 * 20
local CHUNK = 60000 -- bytes of body per UDP packet (localhost datagrams top out near 64 KB)
local MAX_PARTS = 64

function link.init()
  storage.feed = storage.feed or {}
  storage.feed_seq = storage.feed_seq or 0
  storage.clients = storage.clients or {}
  storage.udp_parts = storage.udp_parts or {}
end

function link.client_of(a) return a.client or "rcon" end

function link.push(kind, data, to)
  storage.feed_seq = storage.feed_seq + 1
  local f = storage.feed
  f[#f + 1] = { seq = storage.feed_seq, kind = kind, data = data, to = to }
  if #f > FEED_KEEP then table.remove(f, 1) end
end

function link.online(client)
  local c = client and storage.clients[client]
  return c ~= nil and (game.tick - c.tick) <= ONLINE_TICKS
end

-- The player's own app if it's running, else an operator's orchestrator that hosts serfs for everyone.
function link.client_for_player(index)
  local own = "p" .. index
  if link.online(own) then return own end
  for id, c in pairs(storage.clients) do
    if c.hosts and link.online(id) then return id end
  end
end

-- The server's own serf app (RCON, no player behind it), if one is running.
function link.server_client()
  for id, c in pairs(storage.clients) do
    if not c.player and link.online(id) then return id end
  end
end

-- Everything new for this client since its last poll.
function link.poll(ctx, req)
  local c = storage.clients[ctx.client]
  local fresh = not c
  if fresh then
    c = { cursor = storage.feed_seq } -- a new client starts now, not with old chat
    storage.clients[ctx.client] = c
  end
  c.tick, c.player, c.hosts = game.tick, ctx.player_index, (req.hosts and true or nil)
  local chat, events = {}, {}
  for _, e in ipairs(storage.feed) do
    if e.seq > c.cursor and (not e.to or e.to == ctx.client) then
      if e.kind == "chat" then
        chat[#chat + 1] = e.data
      else
        local a = e.data.agent and storage.agents[e.data.agent]
        if e.to or not a or link.client_of(a) == ctx.client then events[#events + 1] = e.data end
      end
    end
  end
  c.cursor = storage.feed_seq
  local results = {}
  for name, a in pairs(storage.agents) do
    if #a.results > 0 and link.client_of(a) == ctx.client then
      results[name] = a.results
      a.results = {}
    end
  end
  local out = { tick = game.tick, chat = chat, results = results, events = events, client = ctx.client,
    players = #game.connected_players }
  local p = ctx.player_index and ctx.player_index > 0 and game.get_player(ctx.player_index)
  if p then out.you = p.name end
  if fresh and p then
    local owned = false
    for _, a in pairs(storage.agents) do if a.client == ctx.client then owned = true end end
    if not owned then p.print("[serf] Your serf app is connected. Type /serf add to bring in a helper.") end
  end
  return out
end

---------------------------------------------------------------------- UDP
-- Per machine, not game state: only decides whether this machine's socket gets read. recv_udp errors where the
-- game wasn't started with --enable-lua-udp; then try again every 10 s.
-- Always name whose socket to read (0 = the server, else a player): every peer makes the same calls, and only the
-- machine that owns that socket reads anything. (recv_udp() with no argument crashes a headless server, 2.0.77.)
local udp_down_until = 0

-- Framing, both directions: "CC1 <id> <part> <parts>\n<body chunk>".
local function cut(s, i0)
  local i1 = math.min(#s, i0 + CHUNK - 1)
  while i1 < #s do -- don't split a UTF-8 character
    local b = s:byte(i1 + 1)
    if b < 0x80 or b >= 0xC0 then break end
    i1 = i1 - 1
  end
  return s:sub(i0, i1), i1 + 1
end

-- Big replies go out a few packets per tick: a burst larger than the app's socket buffer (208 KB on a default
-- Linux) would be dropped. The queue is per machine like the socket; send_udp is a no-op on every machine but the
-- one that owns the socket, so the queue never affects game state.
local PER_TICK = 3
local outbox = {}

local function flush()
  for _ = 1, PER_TICK do
    local m = table.remove(outbox, 1)
    if not m then return end
    helpers.send_udp(m[1], m[3], m[2])
  end
end

local function send(port, player_index, id, s)
  local parts, i = {}, 1
  repeat
    local chunk
    chunk, i = cut(s, i)
    parts[#parts + 1] = chunk
  until i > #s
  for n, chunk in ipairs(parts) do
    outbox[#outbox + 1] = { port, player_index, "CC1 " .. id .. " " .. n .. " " .. #parts .. "\n" .. chunk }
  end
  flush()
end

function link.udp_tick()
  if outbox[1] then flush() end
  if game.tick < udp_down_until then return end
  local any = pcall(helpers.recv_udp, 0)
  for _, p in pairs(game.connected_players) do
    if pcall(helpers.recv_udp, p.index) then any = true end
  end
  if not any then udp_down_until = game.tick + 600 end
end

function link.on_udp(e, dispatch)
  local id, i, n, body = e.payload:match("^CC1 (%w+) (%d+) (%d+)\n(.*)$")
  if not id then return end
  i, n = tonumber(i), tonumber(n)
  if n < 1 or n > MAX_PARTS or i < 1 or i > n then return end
  local client = "p" .. e.player_index
  if n > 1 then
    local key = client .. ":" .. e.source_port .. ":" .. id
    local p = storage.udp_parts[key] or { got = 0, parts = {}, tick = game.tick }
    storage.udp_parts[key] = p
    if not p.parts[i] then p.parts[i], p.got = body, p.got + 1 end
    if p.got < n then return end
    body = table.concat(p.parts)
    storage.udp_parts[key] = nil
  end
  local reply = dispatch(body, { client = client, player_index = e.player_index, udp = true })
  send(e.source_port, e.player_index, id, reply)
end

function link.gc()
  for key, p in pairs(storage.udp_parts) do
    if game.tick - p.tick > 60 * 60 then storage.udp_parts[key] = nil end
  end
end

return link
