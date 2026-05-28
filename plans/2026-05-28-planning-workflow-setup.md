# Planning Workflow Setup - Bilal Plan

**Date:** 2026-05-28
**Status:** Shipped
**Owner:** Bilal
**Forked from:** [`plan-template.md`](../plan-template.md)

Stand up `~/code` as the top-level parent for many repos, with `~/code/misc` as a git-tracked home for living plans plus a reusable `plan-template.md`. Goal: a durable human↔agent contract so we can curate context in the plan, clear the conversation often, and never lose state across agentic SWE tasks.

---

## 1. How To Use This Template

Fork into `plans/YYYY-MM-DD-<slug>.md`, one per task. Keep the `**Forked from:**` line. Every section below is numbered and **stays in every fork** — never delete one, so the order is absolute. If a section doesn't apply, write `not applicable` plus one line why. **Postmortems is second-to-last and Project History last** — attention on a long doc is U-shaped, so the end stays high-attention; this keeps lessons salient without cluttering the top.

1. How To Use This Template
2. Maintain This Plan
3. Preferences
4. Context & Problem Statement
5. Execution Steps
6. Out of Scope / Non-Goals
7. Architecture
8. Data Snippets — *if relevant*
9. Implementation Details
10. Open Questions / Decisions Needed
11. Test Plan / Acceptance Criteria
12. References / Links
13. File List
14. Long Jobs / Backfill — *optional*
15. Rollback Plan — *optional*
16. Postmortems — *default `not applicable`*
17. Project History — **last**

**500 lines max.** Cut prose first when tight.

---

## 2. Maintain This Plan

- **This is a living document — maintain it constantly.** Update this file the moment anything changes: new info, a decision (even minor), a course change, an experiment result, a postmortem, a new constraint, a status change. Curate context here so we can clear the conversation and resume cold.
- **Own the plan.** Update + commit + push *in the same turn* at every checkpoint above.
- **Be autonomous.** Decide and execute; ask only when blocked or before destructive/irreversible actions.
- **Read before write.** Verify with real data before mutating shared state.
- One status table (the Execution Steps section); move rows as work progresses. Project History is append-only; incidents go to `postmortems/`. Keep the File List current.

*(Setup note: `gh auth login` configured the SSH protocol and registered a key, so `git push` works over SSH even though a bare `ssh -T git@github.com` failed before login.)*

---

## 3. Preferences

- Be autonomous. Decide and execute; ask only when blocked.
- Read before write. Verify with data before mutating shared state.
- Evidence first: problem, observations, decision, implementation.
- TDD by default: cheapest failing test, minimum fix, refactor.
- Plain words. Small steps. Reversible beats clever.
- Push back before destructive actions.
- Commit by filename, never `git add .`. Commit before any build.
- **Clear, jargon-free prose.** Precise technical terms yes; buzzwords and filler no. Dense and transparent — Steinbeck, not David Foster Wallace. Cut any word not earning its place.

---

## 4. Context & Problem Statement

Agentic SWE sessions lose context when the conversation is cleared or compacted. We want a single living document per task that holds the durable state — decisions, architecture, data shapes, steps, tests — so any fresh agent or human can resume cold. This plan sets up the directory layout, git tracking, a generalized template to fork, and the GitHub remote.

**Done looks like:** `~/code/misc` is a git repo containing `plan-template.md` (general-purpose) and this first forked plan, committed and pushed to a GitHub remote; the agent autonomously maintains and pushes plans going forward.

---

## 5. Execution Steps

| # | Task | Status |
|---|------|--------|
| 1 | Create `~/code/` as multi-repo parent | completed |
| 2 | Write generalized `plan-template.md` | completed |
| 3 | Create `~/code/misc` repo with `plans/` + `postmortems/` | completed |
| 4 | Write this first forked plan | completed |
| 5 | `git init` in `misc`, commit docs by filename | completed |
| 6 | Install `gh` | completed |
| 7 | `gh auth login` (browser web flow) | completed — account bilalib1 |
| 8 | `gh repo create` + `git push -u origin main` | completed — github.com/bilalib1/misc |

---

## 6. Out of Scope / Non-Goals

- Building any application — this is workflow scaffolding only.
- CI / pre-commit hooks — not needed for a docs repo yet.
- Migrating existing projects into `~/code` — future, per-repo.

---

## 7. Architecture

```
~/code/                        # top-level parent, NOT a repo; holds many repos
└── misc/                      # git repo (branch: main) -> GitHub remote
    ├── plan-template.md       # fork this per task
    ├── plans/
    │   └── YYYY-MM-DD-<slug>.md
    └── postmortems/
        └── YYYY-MM-DD-<slug>.md
```

Flow: new task -> copy `plan-template.md` to `plans/<dated-slug>.md` -> fill the sections -> work the steps table -> commit + push at each checkpoint. The conversation can be cleared anytime; the plan file is the recovery point.

---

## 8. Data Snippets

Required metadata block at the top of every fork:

```markdown
**Date:** YYYY-MM-DD
**Status:** Plan | In flight | Shipped
**Owner:** [name]
```

Status-table row convention (the load-bearing data structure of the workflow):

```
| 2 | Parse webhook payload | started — schema confirmed, handler stubbed |
```

---

## 9. Implementation Details

1. `mkdir -p ~/code` as the parent for many repos (not itself a repo).
2. Author `plan-template.md`: 17 numbered sections in fixed order — How To Use, Maintain, Preferences, then the body, with Postmortems second-to-last and Project History last; no section is deletable on fork.
3. `mkdir ~/code/misc/{plans,postmortems}`; move template + plan in.
4. Fork the template into this plan as the canonical worked example.
5. `git init` in `misc`, branch `main`, commit by filename (never `git add .`).
6. `brew install gh`.
7. `gh auth login` via browser web flow — sets up SSH protocol and registers a key.
8. `gh repo create misc --private --source=. --remote=origin --push`, then push at each checkpoint thereafter.

---

## 10. Open Questions / Decisions Needed

All resolved as of 2026-05-28:
- **Repo name/visibility:** private repo `misc` (used the default).
- **Auth:** `gh auth login` completed — account `bilalib1`, SSH protocol.
- **Section set + order:** 17 numbered sections, none deletable, Postmortems second-to-last, Project History last — confirmed by Bilal.

---

## 11. Test Plan / Acceptance Criteria

- **Manual check:** `ls ~/code` shows `misc/` (and no top-level `.git`); `ls ~/code/misc` shows `plan-template.md`, `plans/`, `postmortems/`; `git -C ~/code/misc log --oneline` shows the commits; `git -C ~/code/misc status` is clean.
- **Remote check:** `git -C ~/code/misc remote -v` shows `origin`; `git push` succeeds; repo visible on GitHub.
- **Acceptance:** template has all 17 sections in the fixed order; this plan is a valid fork; both files committed and pushed.
- No automated tests — docs + repo scaffolding. Regression guard is the template's own numbered-section list.

---

## 12. References / Links

- `~/code/misc/plan-template.md` — the template this plan forks.
- GitHub remote: https://github.com/bilalib1/misc (private; SSH origin `git@github.com:bilalib1/misc.git`).

---

## 13. File List

- `~/code/` — top-level parent dir for many repos; not a git repo itself.
- `~/code/misc/` — git repo home for planning docs; pushes to GitHub `origin`.
- `~/code/misc/plan-template.md` — general-purpose plan template; fork per task.
- `~/code/misc/plans/2026-05-28-planning-workflow-setup.md` — this plan (first fork / worked example).
- `~/code/misc/postmortems/` — incident writeups (empty for now).

---

## 14. Long Jobs / Backfill

not applicable — no long-running or bulk jobs in this task.

---

## 15. Rollback Plan

Trivially reversible: `rm -rf ~/code/misc` removes the repo. After push, delete the GitHub repo via `gh repo delete`.

---

## 16. Postmortems

not applicable — no prod-visible, costly (\$/compute/time), or high-churn events in this setup task.

---

## 17. Project History

- **2026-05-28** — Set up `~/code` parent + `~/code/misc` repo, generalized `plan-template.md`, first forked plan; pushed to private remote github.com/bilalib1/misc. Initial commit `f351298`.
