# Plan review · Project structure and database plans

- **What changed.** Both follow-up plans were reviewed and revised, and the modernization plan’s top was brought to the same layout. Documentation only: no code, configuration, test or database change.
- **Project structure plan.** It now proposes one folder per service (web page automation, business workflow, puzzle solving, database, reporting, future API) in eleven phases, R0–R10, with an allowed-imports table, a per-move checklist and a risk table. New findings F132–F139. [Project structure plan](../plans/2026-11-25-plan-project-structure.md)
- **Database plan.** It now has a risk table, a backup-and-restore step, a read-only preview account, a privacy rule for the preview and a clock question. New findings F140–F141. [Database plan](../plans/2026-11-25-plan-database-customer-selection.md)
- **Every plan file starts the same way.** Summary bullets, then `## Waiting on the owner` (not finished, questions, confirmations), then `## Questions and answers` in a bulleted format with a suggested answer and an `*open*` slot for the owner. [Modernization plan](../plans/2026-11-23-plan-modernization.md)
- **Agent rules.** `AGENTS.md` and `CLAUDE.md` got the plan-file layout (§8) and a new §9 on expressive names, best practice, documentation and the Q&A format. The old §9 is now §10. Both files are listed in `.gitignore`, so this change is local and not in a commit ([F142](#f142--verified--the-agent-rule-files-are-not-tracked-by-git)).

## How to check

From the project root in PowerShell:

```powershell
git rev-parse --short HEAD
git diff --stat HEAD -- docs
npm run --silent lint:md
Compare-Object (Get-Content AGENTS.md) (Get-Content CLAUDE.md)
git check-ignore -v AGENTS.md CLAUDE.md
```

Expected: the revision this doc was committed on, changes only under `docs/`, `Summary: 0 issues in 0 files`, no output from `Compare-Object` (the two rule files are identical), and both rule files reported by `.gitignore`. The recorded results are in F142–F143.

## F142 · VERIFIED · The agent rule files are not tracked by git

```text
$ git check-ignore -v CLAUDE.md AGENTS.md
.gitignore:178:CLAUDE.md	CLAUDE.md
.gitignore:177:AGENTS.md	AGENTS.md
$ git ls-files | grep -i "agents\|claude"
(no output)
```

The new rules exist only in this working copy. Another checkout or the next developer does not get them unless the owner decides to track the files (see [Open items](#open-items)). The two files are kept identical: `diff -q AGENTS.md CLAUDE.md` printed nothing after the edit. Revision `741166c`.

## F143 · VERIFIED · Documentation only, and lint-clean

The review changed Markdown files only. No file under `src/`, `tests/`, `main.py`, `pyproject.toml` or `uv.lock` was touched. The plan evidence was gathered by reading files and running read-only `git`, `grep`, `wc` and `Select-String` commands. The one Python command used an in-memory loguru sink with dotenv loading disabled, to show which fields loguru writes ([structure plan F136](../plans/2026-11-25-plan-project-structure.md#f136--verified--json-logs-record-the-python-module-name)). No database connection was opened, and the app was not run.

Lint results, markdownlint-cli2 0.24.2 (markdownlint 0.42.2):

```text
npm exec --offline -- markdownlint-cli2 docs/plans/2026-11-25-plan-database-customer-selection.md docs/plans/2026-11-25-plan-project-structure.md
Summary: 0 issues in 0 files
npm exec --offline -- markdownlint-cli2 docs/plans/2026-11-23-plan-modernization.md CLAUDE.md AGENTS.md
Summary: 0 issues in 0 files
```

Whole workspace, `npm run --silent lint:md`: `Linting: 19 files` · `Summary: 0 issues in 0 files`. Gate (ruff, mypy, pytest) and golden master: **NOT RUN**, because no code, configuration or dependency changed.

## Open items

- **Owner question · Track the agent rules in git?** `AGENTS.md` and `CLAUDE.md` are ignored (F142), so the new naming and Q&A rules reach only this machine. **Suggested answer:** remove the two lines from `.gitignore` and commit both files in a `chore:` commit, so every developer and agent gets the same rules. **Owner answer:** *open*
- All questions in the three plans are listed at the top of each plan under `## Waiting on the owner`.
