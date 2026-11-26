# Owner questions moved into one file

- **What is true now.** Every owner question, answer and confirmation of the three plans is in [Owner questions and answers](../plans/2026-11-26-plan-owner-questions-and-answers.md). It has 50 question entries: Modernization Q1–Q10, Database Q1–Q24, Structure Q1–Q15 and Agent rules Q1. It also has the two numbered questions recorded before Phase 1.
- **The plan files keep only the plan.** The [modernization](../plans/2026-11-23-plan-modernization.md), [database](../plans/2026-11-25-plan-database-customer-selection.md) and [project structure](../plans/2026-11-25-plan-project-structure.md) plans keep their `### Questions`, `### Confirmations` and `## Questions and answers` headings (agent rules §8). Each heading now holds one line with a link to the central file.
- **Open.** 19 questions, the open confirmations, and a status conflict on Modernization Q2–Q5 ([F153](#f153--verified--modernization-q2q5-have-answers-but-were-listed-as-open)).
- **Scope.** Documentation only. No code, configuration, test or database change, so the gate and the golden master were **NOT RUN**.

## How to check

From the project root, in PowerShell:

```powershell
$central = 'docs/plans/2026-11-26-plan-owner-questions-and-answers.md'
"central question entries: " + (Select-String -Path $central -Pattern '^- \*\*(Modernization|Database|Structure|Agent rules) Q\d+ ').Count
"central open answers: " + (Select-String -Path $central -Pattern '\*open\*').Count
"question entries left in the three plans: " + (Select-String -Path 'docs/plans/2026-11-23-plan-modernization.md','docs/plans/2026-11-25-plan-database-customer-selection.md','docs/plans/2026-11-25-plan-project-structure.md' -Pattern '^- \*\*Q\d+ ').Count
npm run --silent lint:md
```

Expected output:

```text
central question entries: 50
central open answers: 20
question entries left in the three plans: 0
Linting: 23 files
Summary: 0 issues in 0 files
```

The 20 `*open*` slots are the 19 open questions plus the “How to answer” line at the top of the central file.

## F152 · VERIFIED · The questions moved word for word

**Claim.** The Q&A bullets of the three plans and the two questions in modernization §5 appear in the central file unchanged, apart from two kinds of edit:

- **Plan name in front of each label.** `**Q9 ·` became `**Database Q9 ·`, because each plan numbers its questions from Q1 and the numbers would clash in one file.
- **Link targets rewritten.** A same-plan anchor such as `(#f145--…)` now names its plan file, and a plan’s `#questions-and-answers` link now points at that plan’s group in the central file.

**Evidence.** A Python script read each plan from `git show HEAD:…`, took the lines from `- **Q1 ·` to the next level-2 heading, and blanked every link target (`](…)` → `]()`) and the plan-name prefix in both texts. It then tested whether the HEAD block is contained in the central file. Output:

```text
2026-11-23-plan-modernization.md questions: 10 verbatim: True
2026-11-25-plan-database-customer-selection.md questions: 24 verbatim: True
2026-11-25-plan-project-structure.md questions: 15 verbatim: True
before-Phase-1 item verbatim: True
before-Phase-1 item verbatim: True
```

A second script resolved every relative anchor link in the four plan files, the plan review doc and this doc against GitHub-style heading slugs: `anchor links checked: 405 missing: 3`. All three missing anchors were already there at HEAD ([F154](#f154--verified--three-anchor-links-in-the-modernization-plan-were-already-broken)).

**Other places changed.** Agent rules Q1 came from the [plan review open items](2026-11-25-plan-review-structure-and-database.md#open-items). The original line stays there, with one added line pointing to the central file. The modernization summary has one new bullet linking here. No finding was rewritten.

**Why behavior is unchanged.** Only Markdown files under `docs/` changed. `git status --short` lists four modified files (the three plans and the plan review doc) and two new ones (the central file and this doc).

Base revision `cb8a6a8`, Python 3.14.2, markdownlint-cli2 0.24.2 (markdownlint 0.42.2).

## F153 · VERIFIED · Modernization Q2–Q5 have answers but were listed as open

**Claim.** The answer fields of Modernization Q2–Q5 hold owner answers, but the plan’s Waiting block listed all four as open questions and said “Answered: Q1 and Q6. Partly answered: Q2 and Q5.”

**Evidence.** At HEAD, `docs/plans/2026-11-23-plan-modernization.md` lines 44–47 end with `**Owner answer:** *Yes, as suggested.* for the rest` (Q2, Q5) and `**Owner answer:** *Yes, as suggested.*` (Q3, Q4). `git blame -L44,47` attributes all four lines to `bdb619c`. The [owner answers review](2026-11-26-owner-answers-review.md) line 3 lists only “modernization plan Q6” as answered.

**What this task did.** The answers were not reinterpreted. The central file lists Q2–Q5 as “answered, status to confirm” and asks for a yes or no under [Confirmations](../plans/2026-11-26-plan-owner-questions-and-answers.md#confirmations).

## F154 · VERIFIED · Three anchor links in the modernization plan were already broken

**Claim.** Three links in the body of the modernization plan point at headings that do not exist. This task did not touch those lines.

**Evidence.** The anchor check from F152 printed:

```text
MISSING 2026-11-23-plan-modernization.md -> ../activities/2026-11-24-phase-5-reader-guide.md #branch-checks
MISSING 2026-11-23-plan-modernization.md -> ../../README.md #complete-workflow-catalogue
MISSING 2026-11-23-plan-modernization.md -> ../activities/2026-11-24-phase-5-reader-guide.md #current-guide-corrections
```

`git show HEAD:docs/plans/2026-11-23-plan-modernization.md | grep -c` finds each of the three links once at HEAD, and `git diff` of the plan contains none of them. markdownlint checks link anchors only within one file (MD051), so it does not report them.

## Open items

- **Owner questions.** All of them are in the [central file](../plans/2026-11-26-plan-owner-questions-and-answers.md#waiting-on-the-owner).
- **Agent rules §8–§9.** These rules still say that each plan holds its own Q&A. The central file asks whether they should name the central file instead. `AGENTS.md` and `CLAUDE.md` are not tracked (Agent rules Q1), so this task did not edit them.
- **Older links.** Activity docs written before today still link to `…plan….md#questions-and-answers`. Those links still work and land on the pointer line in each plan. They were left as they are, because old documents are not rewritten.
- **F154.** Fixing the three broken links is a separate `docs:` task.
