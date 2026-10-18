"""A job whose result was claimed by an abandoned wait must still resolve the next wait at once.

Regression: in research-rush round 6, results claimed by a timed-out `act` wait were never seen again, so every
later `wait` sat out its full timeout on jobs that had long finished (25-45% of each agent's hour).

    .venv/bin/python tests/test_job_wait.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crew import game  # noqa: E402


class FakeApi:
    def __init__(self, polls):
        self.polls = list(polls)

    async def call(self, op, **kw):
        assert op == "poll"
        return self.polls.pop(0) if self.polls else {}


async def main():
    game.POLL_SECS = 0.01
    link = game.GameLink("127.0.0.1", 1, "x")
    link.connected.set()
    link.api = FakeApi([{"results": {"claude-1": [{"id": 5, "op": "take", "ok": True, "msg": "took"}]}}])
    abandoned = link.job_future(5)  # an act wait that timed out and walked away
    task = asyncio.create_task(link._poll_loop())
    await asyncio.sleep(0.1)
    assert abandoned.done()
    again = link.job_future(5)  # the next wait on the same job
    assert again.done() and again.result()["ok"], "second wait on a finished job must resolve immediately"
    third = link.job_future(5)
    assert third.done(), "waits stay idempotent"
    task.cancel()
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
