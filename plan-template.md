# [Plan Title] - Bilal Plan Template

**Date:** YYYY-MM-DD
**Status:** Plan | In flight | Shipped
**Owner:** [name]
**Forked from:** [`plan-template.md`](../plan-template.md)

One paragraph: the problem, why it matters, what this plan changes. Replace in every fork.

---

## 1. How To Use This Template

**Repo layout:** `~/code` holds all repos, one directory per repo (this template lives in `~/code/misc`). Plans reference paths relative to their own repo root.

Fork into `plans/YYYY-MM-DD-<slug>.md`, one per task. Keep the `**Forked from:**` line. Every section below is numbered and **stays in every fork** — never delete one, so the order is absolute. If a section doesn't apply, write `not applicable` plus one line why. **Postmortems is second-to-last and Project History last** — attention on a long doc is U-shaped, so the end stays high-attention; this keeps lessons salient without cluttering the top.

1. How To Use This Template
2. Maintain This Plan
3. Preferences
4. Context & Problem Statement
5. Execution Steps
6. Out of Scope / Non-Goals
7. Architecture
8. Implementation Details
9. Data Snippets — *if relevant*
10. Open Questions / Decisions Needed
11. Test Plan / Acceptance Criteria
12. References / Links
13. File List
14. Long Jobs / Backfill — *optional*
15. Rollback Plan — *optional*
16. Postmortems — *default `not applicable`*
17. Project History — **last**

Need an extra section (Risks, Decision Log, Dependencies, Glossary, Build/Deploy, Work Logs)? Insert it just before Project History and renumber from there.

**500 lines max.** Cut prose first when tight.

---

## 2. Maintain This Plan

- **This is a living document — maintain it constantly.** The moment anything changes, update this file: new info, a decision (even a minor one), a course change, an experiment result, a postmortem, a new constraint, a status change. It is a living human↔agent contract — curate context here so we can clear the conversation and resume cold from this file alone.
- **Own the plan.** Update + commit + push *in the same turn* at every checkpoint above.
- **Be autonomous.** Decide and execute. Ask only when blocked or before destructive/irreversible actions.
- **Read before write.** Verify with real data before mutating shared state.
- Keep: decisions + *why*, paths, commands, thresholds, acceptance, rollback, next steps. Drop: diary text, dead alternatives, "we tried X" narration — incidents go to Postmortems.
- One status table (Execution Steps). Move rows `not started` -> `started (status)` -> `completed`.
- Project History is append-only. Keep the File List current. Every new rule needs a test, or a reason none can catch it.

---

## 3. Preferences

*These bias toward caution over speed; for trivial tasks, use judgment.*

- **Be autonomous.** Decide and execute; ask when blocked, genuinely ambiguous, or before destructive/irreversible actions.
- **Think before coding.** State assumptions explicitly. If multiple interpretations exist, present them — don't pick silently. Surface simpler approaches and tradeoffs; push back when warranted. When something is unclear, stop, name it, and ask *before* implementing — not after the mistake.
- **Simplicity first.** Minimum code that solves the problem, nothing speculative — no unrequested features, no abstractions for single-use code, no configurability or error handling for impossible scenarios. If 200 lines could be 50, rewrite. (Boundaries live in §6.)
- **Surgical changes.** Every changed line traces to the request. Match existing style even if you'd do it differently; don't refactor or reformat working code. Remove only the orphans your change created; flag pre-existing dead code, don't delete it.
- **Goal-driven execution.** Turn each task into a verifiable goal ("add validation" → "write tests for invalid inputs, then make them pass"). State a brief plan with a *verify* check per step and loop until verified. (Pairs with TDD; criteria live in §11.)
- **Read before write.** Verify with data before mutating shared state.
- **Evidence first:** problem, observations, decision, implementation.
- **TDD by default:** cheapest failing test, minimum fix, refactor.
- Plain words. Small steps. Reversible beats clever.
- Commit by filename, never `git add .`. Commit before any build.
- **Never write paragraphs.** Use diagrams, bullets, and numbered lists only — never prose blocks. Within them keep words clear and jargon-free: precise technical terms yes; buzzwords and filler no. "We fetch the row once and write all outputs together," not "we leverage a holistic single-pass synergy." Cut any word not earning its place.

---

## 4. Context & Problem Statement

The problem, who has it, why now, and what "done" looks like. State constraints. Current state before desired state.

---

## 5. Execution Steps

Single source of truth for progress. Keep statuses current.

| # | Task | Status |
|---|------|--------|
| 1 | <task> | not started |
| 2 | <task> | started — <brief status> |
| 3 | <task> | completed |

---

## 6. Out of Scope / Non-Goals

Boundaries so scope does not creep. **5 bullets or fewer.** Each: what we deliberately do **not** do, plus why.

- ...

---

## 7. Architecture

How the pieces fit: components, data flow, key interfaces, where this plugs in. A small ASCII diagram beats a paragraph. Note the boundaries we must not touch.

**Drawing the ASCII diagram** — rules for one that's beautiful on a small screen in a markdown viewer:

1. **Flow top→bottom on a centered spine.** Primary flow descends with `▼`; reserve `▲` for genuine back-edges (reads, claims, recovery). A tall, thin diagram beats a wide one.
2. **One concept per box, short label.** 1–3 words, plus an optional parenthetical subtitle line. Never cram pipelines, lists, or multi-step text inside a box.
3. **Detail lives on the edges.** Label each connector beside its `│` with what flows along it (`HTTP POST`, `publish(event)`, `SSE stream`) — not inside the boxes.
4. **Box charset:** `┌ ─ ┐ │ └ ┘`, one space of padding around the label. Outlets are `┬` cut into the bottom border; branches/junctions use `┬ ┴ ├ ┤`. Arrowheads (`▼ ▲`) only at a box's entry.
5. **Align children under their parent's outlets.** Two outlets → two `┬` whose columns equal the child box centers, so the verticals drop straight.
6. **Stay narrow (≤ ~50 visual columns).** Wrapping in a markdown pane destroys alignment. Note: box-drawing/arrow glyphs are multi-byte but render one column wide — count columns, not bytes.
7. **Close with a one-line italic caption** stating the key invariant the boxes can't show (e.g. "Postgres is the only channel between server and worker").

When alignment gets fiddly (branches, centered pairs), build the diagram on a column grid with a throwaway script rather than hand-counting spaces — it guarantees the connectors line up.

Note the boundaries we must not touch.

---

## 8. Implementation Details

Spell out **every key algorithm, loop, and transformation step by step** as a numbered list, in succinct plain English — concrete enough to execute without re-deriving the design. Prefer clear English > pseudocode > code; use code only to name the heavy-lifting library/call (e.g. `torch.nn.functional.scaled_dot_product_attention`, `fast-xml-parser`). One numbered list per algorithm, under a short bold label.

**<name of the algorithm/loop>**

1. ...
2. ...

---

## 9. Data Snippets

*(if relevant — otherwise `not applicable`)*

Ground the work in real shapes. **Include 3 examples** of whatever is central — a JSON payload, an API request/response, a dataset row, ML model in/outputs. **~10 lines each at most** (trim with `...`). Prefer **real queried examples** over invented ones.

```json
{ "example": "replace with a real payload central to this work" }
```

---

## 10. Open Questions / Decisions Needed

The agent's running queue — what's blocked on the human or undecided. Read first on resume. Move resolved items to the relevant section and delete here.

- ...

---

## 11. Test Plan / Acceptance Criteria

### A. E2E / Human Test Plan

The exact end-to-end steps a human runs to confirm it works, with expected outputs (counts, IDs, latencies, screenshots). Followable without questions.

### B. Acceptance Criteria

Concrete true/false conditions that mean done, no judgement calls. (Section 4's "done" is the prose vision; this is the checklist — don't duplicate.)

### C. Automated Tests

The tests we want, each described by the **edge case** it catches (not the happy path). Name the layer; prefer the cheapest catch. Don't commit failing tests; if `main` is already red on unrelated tests, name them.

- Unit: pure logic — `<edge case>`.
- Integration: real local DB/service — `<edge case>`.
- E2E / Playwright: UI and routing (if relevant) — `<edge case>`.
- Production check: curl/query the shipped surface with expected values.

---

## 12. References / Links

Tickets, design docs, dashboards, related plans, external API docs.

- ...

---

## 13. File List

Index of every relevant path: source files touched, configs, data, related docs/plans, external doc URLs — each with a one-line note.

- `path/to/file` — what it is / why it matters.

---

## 14. Long Jobs / Backfill

*(optional — default `not applicable`)*

Any job over ~5 min, bulk writes, or recomputes. "Dataset-only" does not exempt it.

- Use a managed/supervised runner with resource limits; no fire-and-forget processes that starve the app/DB.
- Specify: runner name, claim/version/attempt guards, batch size, sleep, thread caps, progress logging, error capture + flush, alerting, pause/resume + rollback.
- One expensive pass per row: fetch once, run models once, write all outputs together.
- Paid API calls: persist the raw result before the next call (raw output, parsed value, model, prompt hash, config, input id, latency, error, tokens, cost).
- After start, verify the real resource footprint (CPU/memory/affinity) matches the limits.

---

## 15. Rollback Plan

*(optional — `not applicable` if trivially reversible)*

Exact steps + commands to undo a shipped change, and how to tell it worked.

---

## 16. Postmortems

*(default `not applicable`; the moment a trigger fires, write the entry in the same turn)*

Write a postmortem in `postmortems/` for any event **expensive in money, time, or churn** — not just user-facing breakage. Triggers:

- **Prod-visible** regression or outage.
- **Costly:** real money (paid API, GPU/CPU compute) or wall-clock time (long runs, big backfills, long waits).
- **High churn:** many repeated failed attempts, reverts, or commits before it worked.

Each writeup: severity, cost (\$ + time), impact, root cause, UTC timeline, why it slipped through, follow-ups, lessons. Link the fix commit. Add the cheapest regression test/guardrail or say why none can catch it. Add a Project History bullet.

not applicable — no triggering event yet.

---

## 17. Project History

Append-only. One bullet per meaningful shipped unit. (Last.) **At most a couple short sentences per bullet** — what shipped and why, no more. Details belong in their own sections.

- **YYYY-MM-DD** — [what shipped, why, commit SHA or link].
