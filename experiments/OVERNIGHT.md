# The overnight loop

Two layers. The **core** (the mod, the core tools in `crew/tools.py` and `crew/late_tools.py`, the prompt, the
bench) is maintained by people in the day cycle. The **agent layer** (designs, lessons, playbooks, scripts in
`crew/skills.py`'s library) is the serfs' own and grows while they work.

## Rules for the night (from the user, 2026-10-19)

- **Never change the core during the loop**, even for a bug every run hits. Log it with evidence for the morning.
- Allowed overnight: run tests, analyze, keep the instrument working (a broken scenario setup or check, a bench
  crash, a stuck server), and write the morning review. Every instrument fix goes in `nights/<night>/decisions.md`
  with the time and why, and only touches `experiments/` or `tests/bench.py`.
- Budget: Max 20x, use most of it, keep ~30% of the weekly limit. Default `--budget 250` (API-equivalent $) and
  6 in parallel; a usage-limit hit pauses 30 min.

## Running it

    .venv/bin/python experiments/overnight.py --until 07:30 -P 6 --repeat 2
    .venv/bin/python experiments/night_report.py <night> out.html

A second track can run beside it with another model, its own night dir and its own instances, e.g. Opus on the
same tests, fewer at once (2026-10-20). The budget is checked between cycles and holdout-after always runs, so set
it below the real limit:

    .venv/bin/python experiments/overnight.py --suite experiments/suites/opus2.json --night 20261020-opus \
        --variant opus --base-instance 30 -P 2 --repeat 1 --budget 95

Suite keys: `holdout_variant` (who plays the held-out tasks, default the night's variant), `holdout_before`
(false to skip), `holdout_repeat`.

Suite: `experiments/suites/night.json` (train, holdout, long). Phases: holdout-before (fresh library), train
cycles (shared library at `nights/<night>/library`, debrief after every run, a long task every few cycles),
holdout-after (the night's library, read-only).

## Morning review (`nights/<night>/review.md`, rendered at the top of the report)

The user asked for:
1. Where the most time was lost (the "Where the time went" table plus what's behind the biggest buckets).
2. Which tests produced the most diverse data (the diversity table; say what each top test taught).
3. The major challenges, with evidence (run ids, failure counts, debrief quotes).
4. An indexed list of proposed core improvements, each with its data and the expected effect.
5. What the serfs built: scripts and playbooks worth promoting into the core, and junk.

Every morning also write `nights/<night>/requests.md`: the serfs' requests from debriefs and friction notes,
clustered, counted, quoted, and sorted (rendered right under the review).

Sort the serfs' complaints (debriefs, friction) before believing them: a request for a do-everything function
belongs in their own layer; a misconception needs a playbook or a better tool message; real friction is a core
proposal. Most complaints are wrong; a few are the best leads (from the RuneScape Bench talk,
`docs/video-notes-cNm4zyUtWj0.md`).
