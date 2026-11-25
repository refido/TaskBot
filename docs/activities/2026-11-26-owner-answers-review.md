# Owner answers review · Structure and database plans

- **What happened.** The owner answered structure plan Q1–Q12, database plan Q1–Q13 and modernization plan Q6, and confirmed that the two plans never change the same code in the same branch or phase. The answers were checked against the code and recorded in the plans. Documentation only: no code, configuration, test or database change.
- **What is still open.** The answers raised new questions: structure plan Q13–Q15 (tests during restructuring, `import-linter` approval, the one-week rule before R10), database plan Q14–Q24, and modernization plan Q7. Each plan lists them at the top under `## Waiting on the owner`. [Structure plan](../plans/2026-11-25-plan-project-structure.md) · [Database plan](../plans/2026-11-25-plan-database-customer-selection.md) · [Modernization plan](../plans/2026-11-23-plan-modernization.md)
- **What can start.** Structure Phase R0 (glossary and map) and database Phase DB1 (rules and dummy examples) are documentation only, and neither waits on an open question. Structure Phase R1 waits for structure Q13–Q14.
- **New findings.** F144–F146 are in the [database plan](../plans/2026-11-25-plan-database-customer-selection.md#f144--partial--a-restarted-run-does-not-read-the-earlier-runs-itemsjsonl). A restarted run writes to a new folder and does not read the earlier `items.jsonl`. The saved query puts maximum-quota customers before out-of-stock customers, which is the opposite of the owner’s month-start example. `MAX_KUOTA` and the monthly reset work as the owner described, but the reset runs when the app starts.

## How to check

From the project root in PowerShell:

```powershell
git log --oneline -1 -- docs
Select-String -Path docs/plans/*.md -Pattern '\*open\*' | Measure-Object | Select-Object -ExpandProperty Count
npm run --silent lint:md
```

Expected: the commit that adds this doc. The count of `*open*` slots is 18: 15 open questions (structure Q13–Q15, database Q14–Q24, modernization Q7), plus one instruction line at the top of each of the three Q&A sections. Q13 in the structure plan and Q7 in the modernization plan are the same decision. Lint ends with `Summary: 0 issues in 0 files`.

Recorded run, markdownlint-cli2 0.24.2, before commit:

```text
npm run --silent lint:md
Linting: 20 files
Summary: 0 issues in 0 files
```

Code evidence for F144–F146 was read at revision `974451c` (lines quoted in each finding). The gate and the golden master were **NOT RUN**, because only Markdown changed.

## Open items

- The open owner questions are listed at the top of each plan.
- The agent rules (`AGENTS.md`, `CLAUDE.md` §4 and §5) still require `pytest` in the gate. They change once structure Q13 is answered. Both files are untracked (see [F142](2026-11-25-plan-review-structure-and-database.md#f142--verified--the-agent-rule-files-are-not-tracked-by-git)).
