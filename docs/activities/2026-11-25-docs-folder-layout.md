# Docs folder layout

Plans now live in [`docs/plans/`](../plans/) and are named `YYYY-MM-DD-plan-<name>.md`. All other task docs live in [`docs/activities/`](./). Relative links in the moved docs and in the README now point to the new paths. The text of every doc is unchanged apart from those links. [Modernization plan](../plans/2026-11-23-plan-modernization.md) · [Database plan](../plans/2026-11-25-plan-database-customer-selection.md) · [Project structure plan](../plans/2026-11-25-plan-project-structure.md)

## How to check

From the project root, run these PowerShell commands:

```powershell
Get-ChildItem docs -Recurse -File | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1) }
git diff --stat -M 9235ee0 -- docs README.md
```

Expected result: `docs` has no files at its top level, 3 files in `docs\plans` and 11 files in `docs\activities` (including this one). For the 13 files that were moved, the diff shows `129 insertions(+), 129 deletions(-)`, and every changed line is a markdown link.

## F126 · VERIFIED · Docs moved, links rewritten, content otherwise unchanged

The files were moved with `git mv`:

| Old path | New path |
| --- | --- |
| `docs/MODERNIZATION_PLAN.md` | `docs/plans/2026-11-23-plan-modernization.md` |
| `docs/2026-11-25-database-plan.md` | `docs/plans/2026-11-25-plan-database-customer-selection.md` |
| `docs/2026-11-25-project-structure-plan.md` | `docs/plans/2026-11-25-plan-project-structure.md` |
| The other 10 `docs/*.md` files | `docs/activities/<same name>` |

The modernization plan's date, 2026-11-23, is the day it was first committed (`git log --diff-filter=A` → `c3ed06a 2026-11-23`). The two other plans were added in `c7e3105` on 2026-11-25.

A Python script resolved each relative `](target)` link from the file's old location and rewrote it for the new one. Links to the code moved one folder deeper (`../src/...` became `../../src/...`), and links between docs now cross into `../plans/` or `../activities/`. Afterwards, every changed line in `git diff --cached -M -U0` contained a `](` link. Running a filter for changed lines without a link printed nothing.

Two strings look like links but are code inside a recorded snippet: `t["make_reporter"](ROOT,label)` at [phase-1 baseline L2981](2026-11-23-phase-1-behavior-baseline.md#L2981) and L3129. The script changed them at first. I reverted that by hand, so they are byte-identical to before. A link check over the README and all docs reported `checked 268 relative links, broken 2`, both before and after the move. The 2 are those code strings, so the move broke no links. With this doc added, the check reports `checked 276 relative links, broken 4`. The 2 extra hits are the inline-code examples `](target)` and `](ROOT,label)` in this paragraph and the one above it, not real links.

Plain-text paths such as `docs/MODERNIZATION_PLAN.md` inside recorded commands and outputs were **left as they are**. They are evidence of what was run at the time, and §8 says never to rewrite an old finding.

Outside `docs/`, only 3 README links changed: the Phase 5 checks, the quota recovery doc and the Phase 1 test procedure. The local, gitignored `CLAUDE.md` and `AGENTS.md` now give the new plan path and the two folder conventions.

Behavior is unchanged: only Markdown files changed. Checks at `9235ee0` plus this change, with Ruff 0.17.6, mypy 2.4.1 and Python 3.14.2:
`uv run --locked ruff format --check .` → `158 files already formatted`; `uv run --locked ruff check .` → `All checks passed!`; `uv run --locked mypy .` → `Success: no issues found in 144 source files`. `pytest` and the golden-master compare: **NOT RUN**. The change touches Markdown only, and this checkout can reach the real `.env`.

## Open items

- Outside the move, the plan's text was not edited. Its §0/§4 status lines are unaffected.
