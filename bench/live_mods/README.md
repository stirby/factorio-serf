# Mods a live session loads in place of the server's versions

`bench/live_session.py up` adds every zip here to slot 70 (scripts/instance.py `extra_mods`), replacing any other
version of the same mod. A player joining needs the same zip in their own mods folder.

- `Todo-List_19.15.92.zip`: [Todo List](https://github.com/JonasJurczok/factorio-todo-list) by Jonas Jurczok and
  contributors (MIT, `Todo-List-LICENSE`): 19.15.2 plus the remote interface proposed upstream
  (`Todo-List-remote-interface.patch`; review PR https://github.com/stirby/factorio-todo-list/pull/1). 19.15.92 is a
  local version for Factorio 2.0; upstream it would ship as 19.16.0 for Factorio 2.1. jev/todo_bridge.py is the
  serf's side.
