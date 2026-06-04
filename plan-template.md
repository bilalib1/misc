# [Plan Title] - Bilal Plan Template

One paragraph: the problem, why it matters, what this plan changes. Replace in every fork.

---

## 1. How To Use This Template

**Repo layout:** `~/code` holds all repos, one directory per repo (this template lives in `~/code/misc`). Plans reference paths relative to their own repo root.

Fork into `plans/YYYY-MM-DD-<slug>.md`, one per task. Keep the `**Forked from:**` line. Every section below is numbered and **stays in every fork**. If a section doesn't apply, write `not applicable` plus one line why.

1. How To Use This Template
2. Maintain This Plan
3. Preferences
4. Context & Problem Statement
5. Execution Steps
6. Out of Scope / Non-Goals
7. Architecture
8. Database Schema — *optional*
9. Implementation Details
10. Data Snippets — *if relevant*
11. Open Questions / Decisions Needed
12. Test Plan / Acceptance Criteria
13. References / Links
14. File List
15. Long Jobs / Backfill — *optional*
16. Rollback Plan — *optional*
17. Postmortems — *default `not applicable`*
18. Project History — **last**

**500 lines max.** Cut prose first when tight.

---

## 2. Maintain This Plan

- **This is a living document — maintain it constantly.** The moment anything changes, update this file: new info, a decision, a course change, an experiment result, a postmortem, a new constraint, a status change. It is a living human↔agent contract — curate context here so we can clear the conversation and resume cold from this file alone.
- **Own the plan.** Update + commit + push *in the same turn* at checkpoints.
- Keep: decisions + *why*, paths, commands, thresholds, acceptance, rollback, next steps.
- Drop: diary text, dead alternatives, "we tried X" narration, excessive reasoning.
- One status table (Execution Steps). Move rows `not started` -> `started (status)` -> `completed`.
- Project History is append-only. Keep the File List current. Every new rule needs a test, or a reason none can catch it.

---

## 3. Preferences / Best Practices

- **Be autonomous.** Decide and execute; ask when blocked, genuinely ambiguous, or before destructive/irreversible actions.
- **Think before coding.** State assumptions explicitly. Push back against the human when warranted. If multiple interpretations exist, present them — don't pick silently. Surface simpler approaches and tradeoffs.
- **Simplicity first.** Minimum code that solves the problem, nothing speculative — no unrequested features, no abstractions for single-use code, no configurability or error handling for impossible scenarios. If 200 lines could be 50, rewrite. (Boundaries live in §6.)
- **Surgical changes.** Every changed line traces to the request. Refactor when it unblocks the task (duplicated/convoluted code in your path, or to isolate code for a test) — never speculative cleanup of code you're just passing through.
- **Goal-driven execution.** Turn each task into a verifiable goal ("add validation" → "write tests for invalid inputs, then make them pass"). State a brief plan with a *verify* check per step and loop until verified. (Pairs with TDD; criteria live in §12.)
- **Read before write.** Verify with data before mutating shared state.
- **Evidence first:** problem, observations, decision, implementation.
- **TDD by default:** cheapest failing test, minimum fix, refactor.
- Plain words. Small steps. Reversible beats clever.
- **Never write paragraphs.** Use diagrams, bullets, and numbered lists only — never prose blocks. Within them keep words clear and free of jargon/vocab words.
- **Use git cleverly, especially for debugging.**
  - Commit often, by filename (never `git add .`); keep commits atomic — one logical change each — with grep-searchable titles and descriptions.
  - *Debug with history:* `git log`/`blame` to recover intent, `bisect` to find the breaking commit, `reflog` to recover lost state, diff to ground edits.
  - *As useful:* branch/tag a known-good state before risky work; worktrees to explore approaches in parallel.
- **Guard your context.** It degrades as it fills, so spend it deliberately. Reach for `grep -A,B,C`/`find`/`sed/tail/head` to pull only the lines you need instead of reading large files or docs whole; delegate big searches to subagents. Write and checkin python scripts to do tasks we may want to repeat rather than running strings of adhoc commands.
- Delegate all long-running tasks to subagents so as to keep main chat unblocked.

---

## 4. Context & Problem Statement

The problem, who has it, why now, and what "done" looks like. State constraints. Current state before desired state.

---

## 5. Execution Steps

Single source of truth for progress. Keep statuses current.

| # | Task       | Status                       |
| - | ---------- | ---------------------------- |
| 1 | `<task>` | not started                  |
| 2 | `<task>` | started —`<brief status>` |
| 3 | `<task>` | completed                    |

---

## 6. Out of Scope / Non-Goals

Boundaries so scope does not creep. **5 bullets or fewer.** Each: what we deliberately do **not** do, plus why.

- ...

---

## 7. Architecture

How the pieces fit: components, data flow, key interfaces, where this plugs in. A small ASCII diagram beats a paragraph. Note the boundaries we must not touch.

**ASCII diagram rules:** flow top→bottom on a centered spine (`▼` forward, `▲` back-edges); short label per box, detail on the edges beside each `│`; keep it narrow (≤~50 cols);

Example:

```
          ┌────────┐
          │ Client │
          └───┬────┘
              │  POST /test
              ▼
   ┌──────────────────────┐
   │  Ingestion Service   │
   └─────┬──────────┬─────┘
  writes │          │ publish
         ▼          ▼
   ┌───────────┐ ┌─────┐
   │ Datastore │ │ Bus │
   └───────────┘ └──┬──┘
                    │ stream
                    ▼
              ┌───────────┐
              │ Dashboard │
              └───────────┘
```

---

## 8. Databases and Schemas

The **primary table(s)** or any kind of relevant persistent data schemas that this plan reads or writes. For example, could be a local circular queue, or postgres, etc, depending on the project nature. State up front whether it **already exists** (we're using/extending it) or this doc **creates it**, and call out any migration or alter's.

**`<table>`** — one-line purpose. *(new | existing)*

- `PK <col> TYPE` — why this key.
- `<col> TYPE` — note only if non-obvious.
- `<col> TYPE NULL` — filled later by `<step>`.
- *Indexes:* PK `(...)`; `(col, col)` — serves `<read>`. Add others only when a real query needs them, not speculatively.
- *Partitioning/evolution (if relevant):* partition by `<col>` (why); retention `<N>`; new fields added as nullable columns (no rewrite).

---

## 9. Implementation Details

Briefly write **every key algorithm, loop, and transformation step by step** as a numbered list, in succinct plain English — concrete enough to execute without re-deriving the design. Prefer clear English > pseudocode > code; use code only to name the heavy-lifting library/call (e.g. `torch.nn.functional.scaled_dot_product_attention`, `fast-xml-parser`). One numbered list per algorithm, under a short bold label.

**<name of the algorithm/loop>**

1. ...
2. ...

---

## 10. Data Snippets

*(if relevant — otherwise `not applicable`)*

Ground the work in real shapes. **Include 3 examples** of whatever is central — a JSON payload, an API request/response, a dataset row, ML model in/outputs. **~10 lines each at most** (trim with `...`). Prefer **real queried examples** over invented ones.

```json
{ "example": "replace with a real payload central to this work" }
```

---

## 11. Open Questions / Decisions Needed

The agent's running queue — what's blocked on the human or undecided. Read first on resume. Move resolved items to the relevant section and delete here.

- ...

---

## 12. Test Plan / Acceptance Criteria / Repro Steps

### A. E2E / Human Test Plan

One code block with the exact end-to-end steps a human runs to confirm it works, with expected outputs (counts, IDs, latencies, screenshots). Followable without questions.

### B. Acceptance Criteria

Concrete true/false conditions that mean done, no judgement calls.

### C. Automated Tests

Described tests by the edge case it catches. Name the layer. Don't commit failing tests; if `main` is already red on unrelated tests, name them.

- Unit: pure logic — `<edge case>`.
- Integration: real local DB/service — `<edge case>`.
- E2E / Playwright: UI and routing (if relevant) — `<edge case>`.
- Production check: curl/query the shipped surface with expected values.

---

## 13. References / Links

Tickets, design docs, dashboards, related plans, external API docs.

- ...

---

## 14. File List

Index of every relevant path or dir: source files touched, data, related docs/plans, external doc URLs — each with a one-line note.

- `path/to/file` — what it is / why it matters.

---

## 15. Long Jobs / Backfill

*(optional — default `not applicable`)*

Any job over ~5 min, bulk writes, or recomputes.

- Paid API calls or time-consuming compute: stream and persist the raw results 1-by-1 (raw output, parsed value, model, prompt hash, config, input id, latency, error, tokens, cost).
- If you need to test your changes by the outputs of a long-running job, consider setting up a regular agentic loop where you poll and tail logs at appropriate regular intervals (hourly, etc), fixing errors as they come up.

---

## 16. Rollback Plan

*(optional — `not applicable` if trivially reversible)*

Exact steps + commands to undo a shipped change, and how to tell it worked.

---

## 17. Postmortems

*(default `not applicable`; the moment a trigger fires, write the entry in the same turn)*

Write a postmortem in `postmortems/` for any event **expensive in money, time, or churn.** Triggers:

- **Prod-visible** regression or outage.
- **Costly:** real money (paid API, GPU/CPU compute) or wall-clock time (long runs, big backfills, long waits).
- **High churn:** many repeated failed attempts, reverts, or commits before it worked.

Each writeup: severity, cost (\$ + time), impact, root cause, UTC timeline, why it slipped through, follow-ups, lessons. Link the fix commit. Add the cheapest regression test/guardrail or say why none can catch it. Add a Project History bullet.

not applicable — no triggering event yet.

---

## 18. Project History

Append-only. One bullet per meaningful shipped unit. (Last.) **At most a couple short sentences per bullet** — what shipped and why, no more. Details belong in their own sections.

- **YYYY-MM-DD** — [what shipped, why, commit SHA or link].
