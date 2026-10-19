-- "Teach serf": hold a blueprint or blueprint book and click this (or press the key) to put it in your serf's
-- design library.
data:extend {
  {
    type = "custom-input",
    name = "factorio-serf-teach",
    key_sequence = "CONTROL + SHIFT + T",
    consuming = "none",
    action = "lua",
  },
  {
    type = "shortcut",
    name = "factorio-serf-teach",
    order = "z[serf]",
    action = "lua",
    associated_control_input = "factorio-serf-teach",
    icon = "__base__/graphics/icons/blueprint.png",
    icon_size = 64,
    small_icon = "__base__/graphics/icons/blueprint.png",
    small_icon_size = 64,
  },
}
