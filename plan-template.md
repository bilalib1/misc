# [Plan Title] - Bilal Plan Template

**Date:** YYYY-MM-DD
**Status:** Plan | In flight | Shipped
**Owner:** [name]
**Forked from:** [`plan-template.md`](../plan-template.md)

One short paragraph: the problem, why it matters, and what this plan will change. Replace this line in every fork.

---

## How To Use This Template

Fork this file into `plans/YYYY-MM-DD-<slug>.md` for each new task. This is a **living contract between human and agent**: the agent curates context here so we can clear the conversation often and never lose state. A reader (human or freshly-cleared agent) must be able to pick up the work cold from this file alone.

Every fork **must** keep the `**Forked from:**` line in its metadata block, pointing at this template's path (relative to the fork, e.g. `../plan-template.md`). It marks the file as a Bilal plan and lets a cold reader find the meta-rules.

**Numbering.** The preamble — Fork Contract, Warnings, Maintain This Plan, Preferences — is unnumbered, because it is the contract that frames the plan rather than part of the plan body. Everything from Context onward is a numbered section, optional ones included. The fixed order is:

1. Context & Problem Statement
2. Execution Steps
3. Out of Scope / Non-Goals
4. Architecture
5. Data Snippets
6. Implementation Details
7. Open Questions / Decisions Needed
8. Test Plan / Acceptance Criteria
9. Long Jobs / Backfill — *optional*
10. Rollback Plan — *optional*
11. References / Links
12. File List
13. Postmortems — *optional, required once there is a prod-visible regression*
14. Project History — **always last**

**Required** (never delete; if one does not apply, write `not applicable` and one line of why): the unnumbered preamble plus sections 1-8, 11, 12, 14. **Optional:** 9, 10, 13.

**Other optional sections** you may add when they earn their place — Risks & Mitigations, Decision Log, Dependencies / Prerequisites, Glossary, Build / Deploy, Work Logs. Insert each at the logical spot and give it the next number in document order, renumbering what follows.

Keep it brief: **500 lines max.** Prose is the first thing to cut when space is tight.

---

## Fork Contract

Copy this scaffold into every fork. Do not write "same as Bilal." Do not link away the safety rules. If context is tight, cut project prose first but keep: **Fork Contract, Warnings, the Execution Steps table, Tests / Acceptance, Long Jobs / Backfill, Project History.**

The agent operates under these standing rules (see the Preferences section):

- **Be autonomous.** Decide and execute. Ask only when blocked or before destructive/irreversible actions.
- **The plan is the agent's responsibility.** Update + commit + push this file *in the same turn* whenever we hit a checkpoint: a decision, a change of course, a postmortem, a key insight, a research result, a finished experiment, a new constraint, or a status change. Do not wait to be told.
- **Read before write.** Verify with real data before mutating shared state.

---

## Warnings / Brief Postmortems

Short, high-signal traps specific to this project. One bullet each: what bit us, and the one-line prevention. Link full writeups in section 13 (Postmortems). Keep this list pruned — move resolved/stale items out.

- *(example)* **YYYY-MM-DD - <short title>.** What happened in one sentence. Prevention: <the rule>. Postmortem: `postmortems/...md`.

---

## Maintain This Plan

- Update in the same turn when facts, constraints, paths, decisions, findings, postmortems, eval/experiment results, judgement calls, tests, or failures change.
- Keep: decisions + *why*, file paths, commands, thresholds, acceptance criteria, rollback, and next steps.
- Drop: diary text, stale alternatives, "we tried X and it failed" narration. Incident history lives in section 13 (Postmortems), not here.
- Keep **one** status table (section 2). Move rows `not started` -> `started (<brief status>)` -> `completed`. Commit + push between meaningful status/result updates.
- section 14 (Project History) is append-only: one bullet per meaningful shipped unit.
- Keep section 12 (File List) current — it is the index a cold reader uses to find everything.
- Every new rule needs a test, or a stated reason no test can catch it.

---

## Preferences

- Be autonomous. Decide and execute. Ask only when blocked.
- Read before write. Verify with data before mutating shared state.
- Evidence first: problem, observations, decision, implementation.
- TDD by default: cheapest failing test, minimum fix, refactor.
- Plain words. Small steps. Reversible beats clever.
- Push back before destructive actions.
- Commit by filename, never `git add .`. Commit before any build.

**Write plans in clear, jargon-free language.** The reader is an engineer, so precise technical terms are welcome — but buzzwords, filler, and showy vocabulary are not. Aim for dense *and* transparent: every sentence carries information a human can read at a glance. Steinbeck, not David Foster Wallace. Say "we fetch the row once and write all outputs together," not "we leverage a holistic single-pass synergy." If a word is not earning its place, cut it.

---

## 1. Context & Problem Statement

What is the problem, who has it, why now, and what "done" looks like. State the constraints. Ground the reader in the current state before the desired state.

---

## 2. Execution Steps

The single source of truth for progress. Keep statuses current.

| # | Task | Status |
|---|------|--------|
| 1 | <task> | not started |
| 2 | <task> | started — <brief status> |
| 3 | <task> | completed |

---

## 3. Out of Scope / Non-Goals

Explicit boundaries so scope does not creep. **Keep this extra brief: 5 bullets or fewer.** Each is what the plan deliberately does **not** do, plus one line of why.

- ...

---

## 4. Architecture

How the pieces fit: components, data flow, key interfaces, and where this work plugs into the existing system. A small diagram (ASCII is fine) beats a paragraph. Note the boundaries we touch and the ones we must not.

---

## 5. Data Snippets

*(if relevant — otherwise `not applicable`)*

Ground the work in the real shapes we handle. Paste concrete examples in code blocks: a key JSON payload we parse, an API request/response we call, a training-dataset row, or 2-3 example input/outputs of an ML model. Prefer **real queried examples over invented ones** — if we can query the DB/API for samples, include several.

```json
{ "example": "replace with a real payload central to this work" }
```

---

## 6. Implementation Details

Numbered, step-by-step algorithms in **precise plain English**. Order of preference: clear English > pseudocode > code. Use code sparingly — only to name the specific library, API call, or special function that does the heavy lifting (e.g. "use `torch.nn.functional.scaled_dot_product_attention`", "parse with `fast-xml-parser`"). Each step should be concrete enough to execute without re-deriving the design.

1. ...
2. ...

---

## 7. Open Questions / Decisions Needed

Anything blocked on the human, or still undecided — the agent's running queue. A freshly-cleared agent should read this first to see what is open. Move resolved items into the relevant section (or the optional Decision Log if used) and delete them here.

- ...

---

## 8. Test Plan / Acceptance Criteria

- **E2E / manual test plan:** the exact steps a human runs to confirm it works, with expected outputs (counts, IDs, latencies, screenshots).
- **Automated tests:** list the layers that apply and the cheapest one that catches the bug.
  - Unit: pure logic.
  - Integration: against a real local DB/service.
  - E2E / Playwright: UI and routing flows (if relevant).
  - Production check: curl/query the shipped surface with expected values.
- **Acceptance criteria:** the concrete, checkable conditions that mean this is done.
- Do not commit failing tests. If `main` is already red on unrelated tests, name the exact failures.

---

## 9. Long Jobs / Backfill

*(if relevant — otherwise `not applicable`)*

Any job over ~5 minutes, bulk writes, or recomputes. "Dataset-only" does not exempt it.

- Use a managed/supervised runner with resource limits; never fire-and-forget background processes that can starve the primary app or DB.
- Specify: runner name, claim/version/attempt guards, batch size, sleep between batches, thread/concurrency caps, progress logging, error capture + flush, alerting, and pause/resume + rollback.
- One expensive pass per row: fetch inputs once, run models once, write all derived outputs together.
- For paid API calls, persist the raw result before the next call (raw output, parsed value, model, prompt hash, config, input id, latency, error, tokens, cost).
- After start, verify the actual resource footprint (CPU/memory/affinity) matches the limits before walking away.

---

## 10. Rollback Plan

*(optional — `not applicable` if the change is trivially reversible)*

Exact steps + commands to undo a shipped change, and how to tell it worked.

---

## 11. References / Links

Tickets, design docs, dashboards, related plans, external API docs — anything a reader needs to follow the work.

- ...

---

## 12. File List

The index of every relevant path for this work. Keep current. Include source files created/touched, configs, data files, related docs/plans, and external doc URLs — each with a one-line note.

- `path/to/file` — what it is / why it matters.

---

## 13. Postmortems

*(required once there is a prod-visible regression)*

Every prod-visible regression gets a writeup in `postmortems/` in the same turn as the fix.

- Include severity/duration, impact, root cause, UTC timeline, why tests missed it, follow-ups, and lessons.
- Link the fix commit.
- Add the cheapest regression test, or state why it is an ops guardrail no test can catch.
- Add one section 14 (Project History) bullet pointing to the postmortem.

---

## 14. Project History

Append-only. One bullet per meaningful shipped unit.

- **YYYY-MM-DD** — [what shipped, why, commit SHA or link].
