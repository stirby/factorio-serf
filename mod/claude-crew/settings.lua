data:extend({
  {
    type = "bool-setting",
    name = "claude-crew-cheat",
    setting_type = "runtime-global",
    default_value = false,
    order = "a",
  },
  {
    type = "bool-setting",
    name = "claude-crew-player-serfs",
    setting_type = "runtime-global",
    default_value = true,
    order = "b",
  },
  {
    type = "int-setting",
    name = "claude-crew-serfs-per-player",
    setting_type = "runtime-global",
    default_value = 2,
    minimum_value = 0,
    maximum_value = 10,
    order = "c",
  },
})
