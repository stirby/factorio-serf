
## 2026-10-20 08:55 morning: debrief capture (instrument)
- Chat capture got 217 of 378 debriefs and some were the previous turn's last words, not the debrief.
- runs.jsonl rewritten with debriefs read from each transcript (the first reply after the "Time's up" question,
  which arrives as a prompt or inside a tool result): 377 of 377 runs with a transcript. Original kept as
  runs.jsonl.orig.
- tests/bench.py `_debrief` now reads the transcript the same way instead of hooking chat.
