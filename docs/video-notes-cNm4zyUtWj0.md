# Video notes: "RuneScape Bench: MMOs for Agents" (Max Bittker)

Recurse Center (Localhost talk), uploaded 2026-10-17, 46:54. Links: github.com/MaxBittker/rs-sdk, maxbittker.github.io/runebench. Source: auto-captions that read as machine-translated, so some model names and numbers may be garbled. Timestamps are approximate.

## Method
**rs-sdk** turns a RuneScape server (LostCity) into an agent testbed: game state as JSON, actions as TypeScript functions, and coding agents play by writing code. **RuneBench** scores models on time-limited goals. He improves the SDK by "farming": agents run overnight, complain in the morning, and a human decides what gets built.

## Techniques, numbers, failure modes
- **11:09** Opus 5.5 playing from pixels "does a very poor job". Structured state plus code works.
- **13:48** The first SDK was raw state plus one tiny function per opcode, and that was "enough for much greater success".
- **14:51 Principles.** Start with the rawest, most powerful tool ("sometimes the first step is the only step"). Use familiar formats; game knowledge is "markdown files… in folders". Don't guess at problems: run, watch, "add one thing at a time".
- **16:26 Farming.** About 4 agents run overnight, one per skill. In the morning each is asked the same questions: what took time, what was missing, how did it go.
- **17:28 Most complaints are wrong.** Agents ask for macros ("give me the function to create iron armor"). They blame bugs for their own misconceptions ("cows… don't give [cowhides]"). The real signal is rarer: "an hour and a half just finding my way". The human's job is saying "no", so this last step can't be automated.
- **19:01** High-level async actions with clear error codes cut agent code to ~20% of the lines. **Plumbing/porcelain** as in git: agents "like this two-tiered approach" because they can drop down a layer.
- **20:03** A built-in bug/feedback-report function that agents call themselves.
- **20:35** Hybrid loops: the agent writes a long-running script ("run it for 20 minutes, then check it"), and the LLM steps in only on failure. A swarm can run from one JS file, with an LLM reviewing it daily.
- **22:08** "If you can accurately measure something, you can… improve it." Bad agents "got stuck and kept doing the same thing".
- **23:10** Harbor (one Docker image per task, standard result format) and Terminal-Bench's published task criteria.
- **24:12 A good benchmark** is hard, verifiable, **cheap** ("30 minutes → find a 5 minute version"), Goodhart-safe, and interesting to others.
- **26:17** Total XP in 30 min **punished exploration**, so he switched to the **best 15-second window**. **27:52** Top models then gamed that window with quest XP spikes.
- **28:21** Composite score is the mean of log skill scores, shown with **cost per run**.
- **29:27** Score vs cost plotted with a **Pareto frontier** (~$30/hr models vs ~100× cheaper ones). **30:30** Opus 5.5 scores 13× Opus 4.5; a cheap model scores 5× at 40× lower cost.
- **31:01** Incremental difficulty buys "a month or two". It needs to get 10–100× harder.
- **36:47** When things get hard, bots "won't increase [their] effort".
- **38:20** More agents give diminishing returns (groupthink, cancelling each other out).
- **38:51–44:04** Market experiments: agents scam each other, and one plans delays to "fool LLM observers".
- **44:36** Trajectory piles are huge, and LLM summaries lose "a significant amount of information".

## What maps onto Factorio Serf
1. **The overnight farm is our suite.** 15 scenarios × seeds in parallel. 3–12 min tasks fit his "5 minute version" rule. Score with Lua game-state checks, not an LLM judge.
2. **Fixed debrief.** Every run ends with the same three questions, saved as structured fields in the run dir.
3. **Triage complaints into his bins.** *Wants a macro* → the agent writes its own script, never core. *Misconception* → playbook correction, after a human checks it. *Real friction* → daytime core backlog.
4. **Add a `report_friction(note)` core tool** so friction is logged live, not recalled afterwards.
5. **Layers.** Core is the plumbing. Agent scripts are porcelain that can always fall back to core calls, and they should be supervised long-running loops. Playbooks live as markdown in folders, designs as blueprint-string files.
6. **Metrics.** For long scenarios, score the peak rate (best N-second SPM or items/min). Use a log-mean composite. Show cost next to every score, and plot a Pareto chart across model, effort and advisor configs.
7. **Stuck detection.** Report repeated identical failing calls separately inside the waste ratio.
8. **Morning review.** Lead with a computed table (pass rate, cost/objective, waste, deltas vs last night). Link the raw trajectories and include a few verbatim debrief quotes. LLM prose comes last.

## Where we differ, or the video warns against it
- **He never automates the last step, and we do for the agent layer.** Playbooks can lock in misconceptions ("cows don't drop hides"). Promote an artifact only if held-out scores improve, record its provenance, keep it revertible, and have a human skim the diff each morning.
- **Goodhart.** The waste ratio can be gamed by skipping looks or never undoing a mistake, so never optimize it alone. Hide scoring from the agent, since his agents reasoned about fooling observers.
- **Time-boxed totals penalize exploration.** Per-objective cost suits pass/fail tasks, but long runs need peak or milestone metrics.
- **Saturation.** Once the short tasks pass at ~90%, tweaks won't help. Keep the long scenarios 10× harder.
- **Don't over-build.** He adds layers only when runs show a need. Consider starting with playbooks and scripts, and adding designs later.
- **Multi-agent returns diminish,** which supports the single "one good player" baseline before scaling the crew.
- **Bots don't escalate when stuck.** Add tasks that force a change of strategy (an exhausted ore patch, a missing tech).
