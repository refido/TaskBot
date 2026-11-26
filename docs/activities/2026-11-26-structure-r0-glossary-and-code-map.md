# Structure Phase R0 · Glossary and code map

- **What is true now.** Phase R0 of the [project structure plan](../plans/2026-11-25-plan-project-structure.md#phases-proof-and-rollback) is done and waits for owner approval. Two living reference docs exist: the [glossary](../guides/glossary.md) and the [where to look guide](../guides/where-to-look.md).
- **Glossary.** 70 entries in five groups: shop and business terms, database columns, shop page texts, Indonesian words in code names, and TaskBot terms ([F157](#f157--verified--the-glossary-has-70-entries-each-with-a-source)).
- **Guide.** It answers the five R0 questions (a button, a skip decision, a confirmed result, a database write, the final report file) and follows one customer from start to finish. All 145 code links open a line that contains the named symbol ([F158](#f158--verified--every-code-link-in-the-guides-opens-its-named-symbol)).
- **Placement.** The owner chose `docs/guides/` over `src/shared/README.md`, so no folder under `src/` was created ([F159](#f159--verified--the-shared-folder-is-not-created-before-phase-r2)).
- **Found on the way.** Gate step 1 already fails on two Python blocks in older docs ([F160](#f160--verified--ruff-format-already-fails-on-two-python-blocks-in-older-docs), new Modernization Q11). Twelve plan links to `db_query/` point at a folder that does not exist ([F162](#f162--verified--twelve-plan-links-to-db_query-point-at-a-folder-that-does-not-exist)).
- **Scope.** Markdown only: two new guides, this doc, one README line and status lines in three plans. No code, configuration, test or database change.

## How to check

From the project root, in Windows PowerShell 5.1. The first block checks every link in the two guides: the target file exists, each code link’s line contains the symbol in its link text, and each `#anchor` matches a heading.

```powershell
$guides = 'docs/guides/where-to-look.md', 'docs/guides/glossary.md'
$codeLink = '\[`(?<symbol>[^`]+)`\]\((?<path>[^)#]+)#L(?<line>\d+)\)'
$docLink = '\]\((?<path>[^)#]*\.md)?#(?<anchor>[^)L][^)]*)\)'
function Get-Slug([string]$heading) {
    (($heading.ToLowerInvariant() -replace '[^\p{L}\p{Nd} _-]', '') -replace ' ', '-')
}
$codeChecked = 0; $codeMissing = 0; $anchorChecked = 0; $anchorMissing = 0
foreach ($guide in $guides) {
    $folder = Split-Path $guide
    foreach ($match in (Select-String -Path $guide -Pattern $codeLink -AllMatches).Matches) {
        $file = Join-Path $folder $match.Groups['path'].Value
        $text = (Get-Content $file -Encoding UTF8)[[int]$match.Groups['line'].Value - 1]
        $full = $match.Groups['symbol'].Value -replace '\(\)$', ''
        $short = ($full -split '\.')[-1]
        $codeChecked++
        if (-not ($text.Contains($full) -or ($full -match '^[\w.]+$' -and $text.Contains($short)))) {
            $codeMissing++; "NOT ON LINE: $($match.Value)"
        }
    }
    foreach ($match in (Select-String -Path $guide -Pattern $docLink -AllMatches).Matches) {
        $target = if ($match.Groups['path'].Success) { Join-Path $folder $match.Groups['path'].Value } else { $guide }
        $slugs = Select-String -Path $target -Pattern '^#{1,6} (.+)$' -Encoding UTF8 | ForEach-Object { Get-Slug $_.Matches[0].Groups[1].Value }
        $anchorChecked++
        if ($slugs -notcontains $match.Groups['anchor'].Value) { $anchorMissing++; "NO HEADING: $($match.Value)" }
    }
}
$fileChecked = 0; $fileMissing = 0
foreach ($guide in $guides) {
    foreach ($match in (Select-String -Path $guide -Pattern '\]\((?<path>[^)#:]+)(#[^)]*)?\)' -AllMatches).Matches) {
        $fileChecked++
        if (-not (Test-Path (Join-Path (Split-Path $guide) $match.Groups['path'].Value))) { $fileMissing++; "NO FILE: $($match.Value)" }
    }
}
"relative link targets checked: $fileChecked, missing: $fileMissing"
"code links checked: $codeChecked, symbol not on its line: $codeMissing"
"doc anchors checked: $anchorChecked, heading not found: $anchorMissing"
```

Expected output:

```text
relative link targets checked: 162, missing: 0
code links checked: 145, symbol not on its line: 0
doc anchors checked: 13, heading not found: 0
```

When a symbol matches by its last dotted part, for example `PuzzleService.solve` on the line `def solve(`, the check accepts that line. Then the gate steps that this checkout can run, and the Markdown lint:

```powershell
git diff --stat 6a7a97b -- src main.py nik_parser.py user_sessions.py scripts pyproject.toml uv.lock tests
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy .
npm run --silent lint:md
```

Expected output: the `git diff` prints nothing (no code, config or test file changed). Then:

```text
2 files would be reformatted, 167 files already formatted
All checks passed!
Success: no issues found in 144 source files
Linting: 27 files
Summary: 0 issues in 0 files
```

The two unformatted files are older docs ([F160](#f160--verified--ruff-format-already-fails-on-two-python-blocks-in-older-docs)). The count of formatted files went from 164 to 167 because the two new guides and this doc are checked too.

## F157 · VERIFIED · The glossary has 70 entries, each with a source

**Claim.** The [glossary](../guides/glossary.md) explains the terms named in R0 (`NIK`, `KUOTA`, page titles) and the other shop, owner and TaskBot terms a reader meets. Each entry links to the code line that uses it, or to the owner answer for terms the code does not use yet (Lowokwaru, WIB, Rekap Penjualan).

**Evidence.** Rows per section, counted by a PowerShell loop over the table rows under each `##` heading:

```text
Database columns: 10
Indonesian words in today’s code names: 13
Shop and business terms: 12
Shop page texts: 23
TaskBot terms: 12
```

The shop texts were collected with `grep -rn -F "<text>" src main.py nik_parser.py scripts` for each term. Lowokwaru matched no Python file. It appears only in the owner’s git-ignored SQL notebook (`.gitignore:170: db_query/`), so its entry links to the [database plan rule](../plans/2026-11-25-plan-database-customer-selection.md#rules-agreed-with-the-owner) and the owner answer (Database Q2).

**Corrections made while writing.** Two statements in the README were checked against the code and stated more precisely in the glossary:

- The skip limiter’s class defaults are `max_skips: int = 5` and `window_seconds: int = 60` ([rate_limiter.py:158](../../src/web/rate_limiter.py#L158)). The app uses 8 and 48 because `main.py` passes `max_skips=8, window_seconds=48` ([main.py:42](../../main.py#L42)). The README’s “eight skips within 48 seconds” is correct for the app.
- The README calls the sale-page button `GANTI PELANGGAN`. The locator is `page.get_by_role("button", name="Ganti Pelanggan")` ([penjualan_page.py:73](../../src/infrastructure/browser/page_objects/penjualan_page.py#L73)). The glossary quotes the code.

**Why behavior is unchanged.** Markdown only (see the `git diff` in [How to check](#how-to-check)).

Revision `6a7a97b` for every cited line. Python 3.14.2.

## F158 · VERIFIED · Every code link in the guides opens its named symbol

**Claim.** The [where to look guide](../guides/where-to-look.md) answers the five R0 questions, each with an “open this first” link and the path to follow. Every code link in both guides opens a line that contains the symbol named in its link text.

**Evidence.** The link check in [How to check](#how-to-check) printed:

```text
relative link targets checked: 162, missing: 0
code links checked: 145, symbol not on its line: 0
doc anchors checked: 13, heading not found: 0
```

The first run, before this doc existed, printed `symbol not on its line: 5` for four distinct links. They were off by one or two lines: `operator_store.py#L624` (actual 625), `dashboard_page.py#L144` (143), `penjualan_page.py#L18` (20, used twice) and `operator_store.py#L868` (written as 867). All four were fixed before the first commit. That run also printed `NO FILE` twice, for this doc, which did not exist yet.

The same check, run over this doc, the three edited plans and the README, found 381 anchors and 175 link targets. Every miss was already known or a limit of the check: the three anchors of [F154](2026-11-26-centralize-owner-questions.md#f154--verified--three-anchor-links-in-the-modernization-plan-were-already-broken), the `db_query` links of F162, and links in the README, which the check resolves from the wrong folder. None of them is a line this task added.

The five answers, with the code they rest on:

| Question | Where the answer rests |
| --- | --- |
| A button | `self.cek_pesanan_button = page.get_by_role("button", name="CEK PESANAN")` ([penjualan_page.py:58](../../src/infrastructure/browser/page_objects/penjualan_page.py#L58)) |
| A skip decision | `if precheck_action is PrecheckAction.SKIP:` ([transaction_processor.py:179](../../src/orchestration/transaction_processor.py#L179)) |
| A confirmed result | `return self.status == "completed" and bool(self.evidence.strip())` ([transaction_outcome.py:19](../../src/application/models/transaction_outcome.py#L19)), and `TransactionOutcome("completed", evidence="KEMBALI KE HALAMAN UTAMA")` only when that button is visible ([cek_penjualan_page.py:85-87](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L85)) |
| A database write | `with db_connection, db_connection.cursor() as cursor:` ([operator_store.py:625](../../src/infrastructure/database/operator_store.py#L625)). One row per call, because `_DATABASE_BATCH_SIZE = 1` ([account_runner.py:11](../../src/application/services/account_runner.py#L11)) |
| The final report file | `meta_path = run_dir / "run_meta.json"` ([main.py:196](../../main.py#L196)), written from both the `except` and the `else` branch of `main` ([main.py:333](../../main.py#L333), [main.py:347](../../main.py#L347)) |

Revision `6a7a97b` for every cited line.

## F159 · VERIFIED · The shared folder is not created before Phase R2

**Claim.** The R0 row says to write the glossary “in `shared/`’s README”, but the same plan says a target path “becomes real only in its approved phase”, and `shared/` belongs to R2. The owner chose `docs/guides/` when R0 started (asked on 2026-11-26, answer “docs/guides/ (Recommended)”).

**Evidence.** Creating `src/shared/README.md` would have created an importable package two phases early. `src` is a regular package (`Test-Path src\__init__.py` → `True`), and Python treats a subfolder without `__init__.py` inside it as a namespace package, so `import src.shared` would succeed. A throwaway copy of that shape in the scratch folder (`pkg/__init__.py` plus `pkg/sub/README.md`, run with `uv run --no-project python -c "import pkg.sub; print(pkg.sub)"`) printed `<module 'pkg.sub' (namespace) from [...]>`. `Test-Path src\shared` → `False` before and after this task.

**What this changes.** `docs/` now has a third folder next to `plans/` and `activities/` ([docs folder layout](2026-11-25-docs-folder-layout.md)). `docs/guides/` holds living reference docs that later phases update. Dated task records stay in `docs/activities/`. The [structure plan](../plans/2026-11-25-plan-project-structure.md#phases-proof-and-rollback) and the [owner confirmations](../plans/2026-11-26-plan-owner-questions-and-answers.md#confirmations) record the choice, and R2 links to the glossary from `src/shared/README.md`.

## F160 · VERIFIED · Ruff format already fails on two Python blocks in older docs

**Claim.** Before this task, gate step 1 (`ruff format --check .`) failed. Both failures are fenced `python` blocks in Markdown docs, not Python files. Ruff 0.17.6 checks the 22 tracked `.md` files as well as the 144 `.py` files.

**Evidence.** At `6a7a97b`, before any change:

```text
$ uv run --locked ruff format --check .
unformatted: File would be reformatted
  --> docs\activities\2026-11-26-quota-recovery-tool-findings.md:77:6
unformatted: File would be reformatted
   --> docs\plans\2026-11-25-plan-project-structure.md:190:8
2 files would be reformatted, 164 files already formatted
```

`git ls-files` counts 144 `.py` and 22 `.md` files, 166 in total. `git log -S` finds the lines in `cb8a6a8` (recovery doc, recorded evidence script) and `974451c` (structure plan, quoted test line).

**What this task did.** Nothing to those two blocks: one is recorded evidence and the other is a quote, and old findings are not rewritten (agent rules §8). The new guides contain no Python blocks, and `ruff format --check docs/guides` printed `2 files already formatted`. The fix is [Modernization Q11](../plans/2026-11-26-plan-owner-questions-and-answers.md#modernization-plan-questions). Until it is answered, gate step 1 fails on every commit, even a docs-only one. The agent rules say to stop at the first gate failure. These commits went ahead because the failure comes from older docs, which this Markdown-only task did not touch.

Ruff 0.17.6, mypy 2.4.1, markdownlint-cli2 0.24.2.

## F161 · PARTIAL · A new reader still has to try the guide, and the owner has to check the translations

**Claim.** R0 is done when “a new reader can find a button, a skip decision, a confirmed result, a database write and the final report file using only the guide”. The links are proven (F158). Whether a new reader *finds* the answers is not.

**What is missing.**

- A reader who has not seen the code answers the five questions with only the guide. The owner, or someone the owner picks, can do this, as for the [Phase 5 operator guide](2026-11-25-operator-quick-guide.md).
- The English meanings in the glossary are the agent’s translations of the Indonesian shop texts. The code proves the exact Indonesian text, not its meaning. The owner should confirm them.

## F162 · VERIFIED · Twelve plan links to db_query point at a folder that does not exist

**Claim.** Twelve links in two plans use the form `(<../db_query/…>)`. From `docs/plans/` this resolves to `docs/db_query/`, which does not exist. The target files are also git-ignored, so even a corrected path works only on the owner’s machine.

**Evidence.**

```text
$ grep -rno '](<\?\.\./db_query/[^)>]*' docs | wc -l
12
$ Test-Path docs/db_query
False
$ git check-ignore -v 'db_query/basic query.sql'
.gitignore:170:db_query/	db_query/basic query.sql
```

Eight are in the [database plan](../plans/2026-11-25-plan-database-customer-selection.md) and four in the [modernization plan](../plans/2026-11-23-plan-modernization.md) (`grep … | cut -d: -f1 | sort | uniq -c`). The [docs move](2026-11-25-docs-folder-layout.md) rewrote `../src/…` links. Whether its script skipped the `<…>` link form is **UNVERIFIED**. This task did not change those links.

## Open items

- **Owner approval of R0 (F161).** Try the guide’s five questions, and check the English meanings in the glossary. R1 starts after approval.
- **Modernization Q11 (F160).** Choose how Ruff treats Python blocks in Markdown. [Question](../plans/2026-11-26-plan-owner-questions-and-answers.md#modernization-plan-questions)
- **F162.** Fixing the twelve `db_query` links is a separate `docs:` task. It needs a decision on linking to git-ignored files.
- **Agent rules §9.** The rules require a glossary entry for each domain term but do not say where the glossary is. `AGENTS.md` and `CLAUDE.md` are not tracked (`.gitignore:177-178`), so this task did not edit them. Tracking them is approved (Agent rules Q1) and still to be done.
- **Keeping line links current.** The guides link to lines at `6a7a97b`. A later phase that moves or edits a cited module updates the links and reruns the check in [How to check](#how-to-check).
- **NOT RUN.** `pytest` and the golden master. This task changed Markdown only, and this checkout can reach the real `.env` (agent rules §4). The golden master is required only for code, config or dependency changes (agent rules §5).
