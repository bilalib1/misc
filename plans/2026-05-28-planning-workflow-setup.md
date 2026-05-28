# Planning Workflow Setup - Bilal Plan

**Date:** 2026-05-28
**Status:** Shipped
**Owner:** Bilal
**Forked from:** [`plan-template.md`](../plan-template.md)

Stand up `~/code` as the top-level parent for many repos, with `~/code/misc` as a git-tracked home for living plans plus a reusable `plan-template.md`. Goal: a durable human↔agent contract so we can curate context in the plan, clear the conversation often, and never lose state across agentic SWE tasks.

---

## Fork Contract

- **Be autonomous.** Decide and execute; ask only when blocked or before destructive/irreversible actions.
- **The plan is the agent's responsibility.** Update + commit + push this file in the same turn at every checkpoint (decision, change of course, postmortem, insight, research/experiment result, new constraint, status change).
- **Read before write.** Verify with real data before mutating shared state.

---

## Warnings / Brief Postmortems

- not applicable — no traps hit. (Setup note: `gh auth login` configured the SSH protocol and registered a key, so `git push` works over SSH even though a bare `ssh -T git@github.com` failed before login.)

---

## Maintain This Plan

- Keep one status table (section 2); move rows as work progresses, commit + push between meaningful updates.
- Keep section 13 (File List) current.
- Project History is append-only; incidents go to `postmortems/`.

---

## 1. Context & Problem Statement

Agentic SWE sessions lose context when the conversation is cleared or compacted. We want a single living document per task that holds the durable state — decisions, architecture, data shapes, steps, tests — so any fresh agent or human can resume cold. This plan sets up the directory layout, git tracking, a generalized template to fork, and the GitHub remote.

**Done looks like:** `~/code/misc` is a git repo containing `plan-template.md` (general-purpose) and this first forked plan, committed and pushed to a GitHub remote; the agent autonomously maintains and pushes plans going forward.

---

## 2. Execution Steps

| # | Task | Status |
|---|------|--------|
| 1 | Create `~/code/` as multi-repo parent | completed |
| 2 | Write generalized `plan-template.md` (final section set + order) | completed |
| 3 | Create `~/code/misc` repo with `plans/` + `postmortems/` | completed |
| 4 | Write this first forked plan | completed |
| 5 | `git init` in `misc`, commit docs by filename | completed |
| 6 | Install `gh` | completed |
| 7 | `gh auth login` (browser web flow) | completed — account bilalib1 |
| 8 | `gh repo create` + `git push -u origin main` | completed — github.com/bilalib1/misc |

---

## 3. Out of Scope / Non-Goals

- Building any application — this is workflow scaffolding only.
- CI / pre-commit hooks — not needed for a docs repo yet.
- Migrating existing projects into `~/code` — future, per-repo.

---

## 4. Architecture

```
~/code/                        # top-level parent, NOT a repo; holds many repos
└── misc/                      # git repo (branch: main) -> GitHub remote
    ├── plan-template.md       # fork this per task
    ├── plans/
    │   └── YYYY-MM-DD-<slug>.md
    └── postmortems/
        └── YYYY-MM-DD-<slug>.md
```

Flow: new task -> copy `plan-template.md` to `plans/<dated-slug>.md` -> fill required sections -> work the steps table -> commit + push at each checkpoint. The conversation can be cleared anytime; the plan file is the recovery point.

---

## 5. Postmortems

not applicable — no prod-visible, costly (\$/compute/time), or high-churn events in this setup task.

---

## 6. Data Snippets

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

## 7. Implementation Details

1. `mkdir -p ~/code` as the parent for many repos (not itself a repo). *(done)*
2. Author `plan-template.md`: required sections = Fork Contract, Warnings, Maintain, numbered 1-7, Out of Scope, Open Questions, References/Links, File List, Project History (last). Rollback optional. App-specific build/cgroup rules generalized into optional guidance. *(done)*
3. `mkdir ~/code/misc/{plans,postmortems}`; move template + plan in. *(done)*
4. Fork the template into this plan as the canonical worked example. *(done)*
5. `git init` in `misc`, branch `main`, commit by filename (never `git add .`). *(in progress)*
6. `brew install gh`. *(done)*
7. `gh auth login` via browser web flow — no SSH key required; sets up HTTPS auth in `osxkeychain`.
8. `gh repo create bilal/misc --private --source=. --remote=origin --push` (or equivalent), then push at each checkpoint thereafter.

---

## 8. Open Questions / Decisions Needed

All resolved as of 2026-05-28:
- **Repo name/visibility:** private repo `misc` (used the default).
- **Auth:** `gh auth login` completed — account `bilalib1`, SSH protocol.
- **Required section set:** Out of Scope, Open Questions, References, File List required; Rollback optional — confirmed by Bilal.

---

## 9. Test Plan / Acceptance Criteria

- **Manual check:** `ls ~/code` shows `misc/` (and no top-level `.git`); `ls ~/code/misc` shows `plan-template.md`, `plans/`, `postmortems/`; `git -C ~/code/misc log --oneline` shows the setup commit; `git -C ~/code/misc status` is clean.
- **Remote check:** `git -C ~/code/misc remote -v` shows `origin`; `git push` succeeds; repo visible on GitHub.
- **Acceptance:** template has all required sections in the fixed order with Project History last; this plan is a valid fork; both files committed and pushed.
- No automated tests — docs + repo scaffolding. Regression guard is the template's own required-sections checklist.

---

## 10. Long Jobs / Backfill

not applicable — no long-running or bulk jobs in this task.

---

## 11. Rollback Plan

Trivially reversible: `rm -rf ~/code/misc` removes the repo; nothing is published until step 8. After push, delete the GitHub repo via `gh repo delete`.

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

## 14. Project History

- **2026-05-28** — Set up `~/code` parent + `~/code/misc` repo, generalized `plan-template.md`, first forked plan; pushed to private remote github.com/bilalib1/misc. Initial commit `f351298`.
