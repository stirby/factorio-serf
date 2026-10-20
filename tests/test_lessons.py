"""Lessons: rules the serf is taught, kept across worlds, shown every turn, logged with their context.

    .venv/bin/python tests/test_lessons.py
"""
import asyncio
import json
import os
import sys
import tempfile
from collections import deque
from pathlib import Path
from types import SimpleNamespace

os.environ["SERF_LESSONS_DIR"] = tempfile.mkdtemp(prefix="serf-lessons-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crew import lessons  # noqa: E402
from crew.tools import t_lesson  # noqa: E402

D = Path(os.environ["SERF_LESSONS_DIR"])


def test_store():
    assert lessons.load() == [] and lessons.render() == ""
    assert lessons.add("  - Never route pipes next to other fluid lines.  ").startswith("lesson saved")
    assert lessons.add("never route pipes next to other fluid lines.") == "already a lesson"
    assert lessons.add("   ").startswith("error")
    lessons.add("Ask before removing anything you didn't build.")
    assert lessons.render() == ("1. Never route pipes next to other fluid lines.\n"
                                "2. Ask before removing anything you didn't build.")
    assert lessons.add("x", replaces=5).startswith("error")
    assert lessons.add("Keep belts carrying different items apart.", replaces=1).startswith("lesson updated")
    assert lessons.load()[0] == "Keep belts carrying different items apart."
    # the user edits the file by hand: comments and blank lines are ignored
    (D / "lessons.md").write_text("# my serf's rules\n\n" + (D / "lessons.md").read_text())
    assert len(lessons.load()) == 2
    for i in range(lessons.MAX_LESSONS - 2):
        lessons.add(f"rule {i}")
    assert lessons.add("one too many").startswith("error")
    log = [json.loads(line) for line in (D / "lessons.jsonl").read_text().splitlines()]
    assert log[2]["replaced"] == "Never route pipes next to other fluid lines."


async def test_tool():
    (D / "lessons.md").unlink()
    said = []

    async def notice(text):
        said.append(text)

    agent = SimpleNamespace(name="serf", recent_human=deque(["otterplex: @serf you mixed my acid into the water"]),
                            orch=SimpleNamespace(cfg=SimpleNamespace(state_dir=Path("/x/world-42"))), notice=notice)
    out = await t_lesson(agent, {"text": "Never connect a new pipe to a pipe carrying another fluid."})
    assert out.startswith("lesson saved") and said == ["learned: Never connect a new pipe to a pipe carrying another fluid."]
    last = json.loads((D / "lessons.jsonl").read_text().splitlines()[-1])
    assert last["world"] == "world-42" and last["context"] == ["otterplex: @serf you mixed my acid into the water"]
    await t_lesson(agent, {"text": "never connect a new pipe to a pipe carrying another fluid."})
    assert len(said) == 1  # a duplicate isn't announced


if __name__ == "__main__":
    test_store()
    asyncio.run(test_tool())
    print("ok")
