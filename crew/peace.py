"""Biters off, for test worlds only: every test and benchmark server goes through this (scripts/instance.py,
scripts/server.sh). Removes every enemy-force entity on every surface, turns on peaceful mode, stops expansion and
evolution, and stops new enemy bases generating. It changes the save for good, so never run it on a world people
play; tests always run on copies."""
from __future__ import annotations

BITERS_OFF_LUA = """
local removed = 0
game.map_settings.enemy_expansion.enabled = false
game.map_settings.enemy_evolution.enabled = false
for _, s in pairs(game.surfaces) do
  s.peaceful_mode = true
  pcall(function() game.forces.enemy.set_evolution_factor(0, s) end)
  pcall(function()
    local mgs = s.map_gen_settings
    for name, c in pairs(mgs.autoplace_controls or {}) do
      if name:find("enemy") then c.frequency = 0; c.size = 0 end
    end
    s.map_gen_settings = mgs
  end)
  for _, e in pairs(s.find_entities_filtered { force = "enemy" }) do
    if e.valid then e.destroy(); removed = removed + 1 end
  end
end
return { removed = removed }
"""


async def biters_off(crew) -> dict:
    """`crew` is a crew.rcon.Crew. Returns {"removed": n}."""
    r = await crew.call("eval", code=BITERS_OFF_LUA)
    return r.get("result") if isinstance(r, dict) else r
