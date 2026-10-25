# Mods a live session loads in place of the server's versions

`bench/live_session.py up` adds every zip here to slot 70 (scripts/instance.py `extra_mods`), replacing any other
version of the same mod. A player joining needs the same zip in their own mods folder.

- `Todo-List_19.15.90.zip`: [Todo List](https://github.com/JonasJurczok/factorio-todo-list) by Jonas Jurczok and
  contributors (MIT, `Todo-List-LICENSE`), 19.15.2 plus a remote interface so the serf can take tasks assigned to it
  (`Todo-List-remote-interface.patch`; jev/todo_bridge.py is the serf's side). 19.15.90 is a local version number
  until the change is offered upstream.
