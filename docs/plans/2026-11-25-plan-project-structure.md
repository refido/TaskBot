# Project structure plan · One folder per service, named for its job

- **Goal.** Make the project readable at a glance: one top-level folder per service, each named for its job. The services are web page automation, business workflow, puzzle solving, database, reporting and a future API. Behavior stays the same in every phase.
- **Why.** Today the folder names do not say what lives inside. `src/web/` holds the reporter and rate limiting, and the puzzle code is spread over three folders. Imports cross between layers in both directions ([F132](#f132--verified--folder-names-do-not-say-what-lives-inside)–[F134](#f134--verified--imports-cross-the-layers-in-both-directions)).
- **How.** Eleven small phases, R0 to R10. Each phase moves one service, keeps the old import path working, and passes the agreed checks and the golden master. Splitting big files and removing old paths are separate, later phases.
- **Status.** R0 can start. Use focused existing tests and the golden master. Keep Ruff and mypy. [Owner decisions](2026-11-26-plan-owner-questions-and-answers.md)
- **Related.** [Database plan](2026-11-25-plan-database-customer-selection.md) · [Modernization plan](2026-11-23-plan-modernization.md) · [Agent rules](../../AGENTS.md)

## Waiting on the owner

### Not finished

- All phases, R0 to R10, are proposals. None has started.
- The earlier S1–S6 phases are replaced by R0–R10 ([mapping](#how-the-earlier-s1s6-phases-map-to-the-new-phases)).
- The agent rules (§4 and §5) still require `pytest` in every commit’s gate. The approved Q13 exception still needs to be reflected in the rules.

### Questions

Every question for this plan, with its suggested and owner answers, is in [Owner questions and answers](2026-11-26-plan-owner-questions-and-answers.md#project-structure-plan-questions). Structure Q1–Q15 are answered. Q14 supersedes the earlier tool choice in Q8.

### Confirmations

Open and confirmed decisions are in [Owner questions and answers · Confirmations](2026-11-26-plan-owner-questions-and-answers.md#confirmations). The owner confirmed separate move and split phases and one branch, document and approval per phase.

## Questions and answers

Moved on 2026-11-26 to [Owner questions and answers](2026-11-26-plan-owner-questions-and-answers.md#project-structure-plan-questions), word for word. A question number in this plan, such as Q9, is the same number in that file.

## Proposed target layout

A path below becomes real only in its approved phase. The old path keeps working until Phase R10 ([F137](#f137--verified--old-import-paths-already-have-a-safety-test)).

```text
main.py                          Command-line entry point. Stays at the root, gets thinner.
src/
├── command_line/                Read settings, build the run, start it, print the run summary
├── business_workflow/           BUSINESS WORKFLOW SERVICE: what happens to each customer, and why
│   ├── operator_run/            Run one operator account from login to the last customer
│   ├── customer_transaction/    Prechecks, sale, outcome and skip decisions for one customer
│   ├── session_recovery/        Recover an expired shop session
│   ├── pacing/                  Skip and customer-update rate limits
│   └── service_interfaces.py    What the workflow needs from the other services (typing Protocols)
├── web_automation/              WEB PAGE AUTOMATION SERVICE: the only place that knows the shop's DOM
│   ├── browser_session/         Start and stop Playwright, detect the login page
│   ├── pages/                   One module per shop page: login, dashboard, sales, sales check, customer update, consent
│   ├── dialogs/                 One module per pop-up: customer type, warnings, update required/confirm/success
│   ├── puzzle_capture/          Read the puzzle images and the slider from the page
│   └── page_observation/        Precheck observer and interaction diagnostics
├── puzzle_solving/              PUZZLE SOLVING SERVICE: images in, slider movement out
│   ├── puzzle_solving_service.py  The one entry the business workflow calls
│   ├── image_matching/          Find where the piece fits (OpenCV/NumPy)
│   └── slider_movement/         Turn the match into a drag and check success
├── database/                    DATABASE SERVICE: PostgreSQL reads and writes
│   ├── operator_quota_store/    Operator tables, quota rules, monthly reset
│   └── quota_delivery/          Report-to-database sync, quota journal, receipts, recovery
├── reporting/                   REPORT SERVICE: what is written about a run
│   ├── transaction_report_coordinator.py  Today's reporter: stage, write files, queue database sync
│   ├── report_files/            CSV/JSONL writing and reading
│   └── run_summaries/           Analytics, classification, console summary, run metadata
├── api/                         API SERVICE (prepared, not served): read-only operations and response models
├── session_export/              The user-session export tool
└── shared/                      Settings, logging, privacy masking, path helpers, glossary
```

### Which service may import which

The arrow means “may import”. Every service may import `shared`. No other import is allowed. Review imports against this table during each move (Q14).

| Service | May import | Must never import |
| --- | --- | --- |
| `command_line` | every service | — |
| `business_workflow` | `web_automation`, `puzzle_solving`, `database`, `reporting` (later only through `service_interfaces.py`) | `api`, `command_line` |
| `web_automation` | — | every other service. Today page objects import workflow models ([F134](#f134--verified--imports-cross-the-layers-in-both-directions)). Those models move to a neutral place first. |
| `puzzle_solving` | — | `web_automation` (it receives images, it does not read the page) |
| `database` | — | `reporting`. Today the database sync imports the reporter ([F134](#f134--verified--imports-cross-the-layers-in-both-directions)). |
| `reporting` | — | `database`, `web_automation` |
| `api` | `reporting`, `database` (read side only) | `web_automation`, `business_workflow`. An API read can never start a sale. |

### Where today’s modules go

| Today | Target service | Note |
| --- | --- | --- |
| `src/config.py`, `src/infrastructure/config/`, `src/logging_utils.py`, `src/privacy.py`, `src/path_utils.py` | `shared` | Moved first, because everything imports them. |
| `src/infrastructure/browser/`, `src/web/pages/` (old paths), `src/web/session_state.py`, `src/infrastructure/interaction_diagnostics.py` | `web_automation` | `src/web/pages/` already re-exports the page objects. |
| `src/web/helpers.py` (`Helpers`) | `web_automation/puzzle_capture` | It saves puzzle images from the page. The class name `Helpers` gets an expressive name, such as `PuzzleImageCapture`. |
| `src/application/services/puzzle_service.py`, `src/vision/`, `src/pipelines/` | `puzzle_solving` | Three folders become one ([F133](#f133--verified--the-puzzle-code-lives-in-three-folders)). |
| `src/infrastructure/database/`, `scripts/db_management.py` (command stays) | `database` | The folder already reads clearly. The sync’s reporter import is removed first. |
| `src/web/reporter.py`, `src/infrastructure/reporting/` | `reporting` | Keep the order: stage → CSV → JSONL → queue database ([F124](#f124--verified--the-order-of-saving-a-result-matters)). |
| `src/orchestration/`, `src/application/services/` (rest), `src/application/use_cases/process_account.py`, `src/application/models/`, `src/web/rate_limiter.py` | `business_workflow` | Moved last, because it imports everything else. |
| `src/application/use_cases/export_session.py`, `src/infrastructure/sessions/`, `user_sessions.py` (command stays) | `session_export` | A separate tool with its own command. |
| — | `api` | New, in Phase R9. |

## F123 · VERIFIED · The CLI already connects the pieces

In `_build_account_runner`, the CLI passes `browser_session_factory=BrowserSession`, `transaction_processor_factory=TransactionProcessor` and `report_syncer=DatabaseReportSyncer()`. The account runner receives these objects, and `run_account` passes that runner to `process_account`. This gives us a place to change an implementation without giving each caller its own setup code. [CLI wiring](../../main.py#L101) · [CLI delegation](../../main.py#L123) · [Runner](../../src/application/services/account_runner.py#L20)

| If you want to know… | Open this first | What the source shows |
| --- | --- | --- |
| Where does the app find and use a page? | [Browser session](../../src/infrastructure/browser/playwright_session.py#L24) and [dashboard page](../../src/infrastructure/browser/page_objects/dashboard_page.py#L136) | The browser has its own session class. The old web dashboard module already re-exports the page class. [Old import](../../src/web/pages/dashboard.py#L1) |
| Who gets processed, skipped or stopped? | [Customer loop](../../src/orchestration/transaction_processor.py#L95) and [precheck decisions](../../src/application/services/transaction_prechecks.py#L167) | The loop takes the configured customers in order. A stock exception breaks the loop. Prechecks distinguish ready, expired session and refusal. |
| What does the puzzle stage return? What makes a sale count? | [Puzzle result](../../src/application/services/puzzle_service.py#L13) and [sale outcome](../../src/application/models/transaction_outcome.py#L13) | The puzzle result carries a solved flag and attempt counts. The sale check separately requires `self.status == "completed" and bool(self.evidence.strip())`. Someone changing reporting needs the second rule. |
| Where do quota and recovery live? | [Operator store](../../src/infrastructure/database/operator_store.py#L300), [DB sync](../../src/infrastructure/database/report_syncer.py#L22) and [quota journal](../../src/infrastructure/database/quota_journal.py#L33) | The store constructs a quota delta, the syncer manages report-row delivery, and the journal has a destination/operator context. The operator SQL already has its own module. [Quota arithmetic](../../src/infrastructure/database/_operator_sql.py#L93) |
| Who saves the customer result? | [Reporter](../../src/web/reporter.py#L1134) and [file writer](../../src/infrastructure/reporting/file_writer.py#L60) | The reporter stages quota delivery, calls the file writer and queues the DB sync. The writer appends CSV and then JSONL. Moving the reporter changes several callers even though its folder says “web”. |

Rechecked at `741166c`: the cited lines are unchanged, and no file under `src/` or `main.py` changed since `db5e95a` (see [How to check](#how-to-check)).

## F124 · VERIFIED · The order of saving a result matters

In the reporter, `self.file_writer.append_row(row)` precedes `self._queue_row_for_batch_sync(row)`. A named contract test covers persistence, sync and summary order. A separate test covers an unconfirmed sale and prevents retrying it. These are starting checks for any move near those boundaries. [Write and queue](../../src/web/reporter.py#L1134) · [Persistence contract](../../tests/contract/test_reporting_and_main.py#L65) · [Unconfirmed-sale contract](../../tests/contract/test_transaction_processor.py#L855)

## F132 · VERIFIED · Folder names do not say what lives inside

`src/web/` holds the 1,483-line reporter, the rate limiter, the login-page check and a puzzle-image class named `Helpers`. The pages in `src/web/pages/` are 3-line re-exports of `src/infrastructure/browser/page_objects/`. The customer loop lives in `src/orchestration/`, but the precheck and puzzle steps it calls live in `src/application/services/`. A reader looking for “the web part” or “the business part” has to open several folders.

```text
$ wc -l src/web/*.py src/web/pages/dashboard.py
   185 src/web/helpers.py        216 src/web/rate_limiter.py
  1483 src/web/reporter.py        35 src/web/session_state.py
     3 src/web/pages/dashboard.py
```

[Old dashboard import](../../src/web/pages/dashboard.py#L1) · [`Helpers` class](../../src/web/helpers.py#L36)

The biggest modules are the candidates for the later split phase (R8). Line counts are from `wc -l` at `741166c`: `dashboard_page.py` 2,154 · `reporter.py` 1,483 · `operator_store.py` 1,297 · `transaction_prechecks.py` 1,162 · `puzzle_solver.py` 897 · `interaction_diagnostics.py` 875 · `transaction_processor.py` 850.

## F133 · VERIFIED · The puzzle code lives in three folders

The puzzle step has its entry in `src/application/services/puzzle_service.py`, the image matching in `src/vision/` (`puzzle_solver.py` plus `src/vision/puzzle/`) and the slider drag in `src/pipelines/slider/`. The customer loop imports both the slider function and the solver class directly:

```python
# src/orchestration/transaction_processor.py:L31-L33
from src.pipelines.solve_slider import solve_slider_with_puzzle
from src.privacy import artifact_nik
from src.vision.puzzle_solver import PuzzleSolver
```

[Imports](../../src/orchestration/transaction_processor.py#L31) · [Slider calls the solver](../../src/pipelines/slider/solver.py#L125)

## F134 · VERIFIED · Imports cross the layers in both directions

The `infrastructure` folder should not depend on `application` or `web`, but it does:

```text
src/infrastructure/browser/page_objects/base_page.py:6:from src.web.session_state import SessionExpiredError, is_login_page
src/infrastructure/browser/page_objects/cek_penjualan_page.py:6:from src.application.models.transaction_outcome import TransactionOutcome
src/infrastructure/browser/page_objects/customer_update_page.py:7:from src.application.models.customer_workflow import (
src/infrastructure/database/report_syncer.py:17:from src.web.reporter import TransactionReporter
```

`src/application/__init__.py` loads its services lazily to avoid an import cycle with the page objects. Its comment says: “Importing an application model must not eagerly import services that depend on the page object currently importing that model.” [Lazy exports](../../src/application/__init__.py#L3) · [Database sync imports the reporter](../../src/infrastructure/database/report_syncer.py#L17)

This is why the phases move the shared outcome models to a neutral place *before* they move the services that use them. Import order has side effects here (agent rules §2), so a cycle is a stop condition.

## F135 · VERIFIED · Tests swap out names on the module that uses them

Tests replace functions with `monkeypatch.setattr(<module>, "<name>", …)`. No test uses a dotted string path. Counts, from the command in [How to check](#how-to-check):

```text
     31 monkeypatch.setattr(taskbot_main
     19 monkeypatch.setattr(transaction_processor
     19 monkeypatch.setattr(reporter
     10 monkeypatch.setattr(export
      8 monkeypatch.setattr(reporting
      6 monkeypatch.setattr(operator_store
```

If `transaction_processor.py` moves and the old path only re-exports it, `monkeypatch.setattr(old_module, …)` changes the old module, which the moved code no longer reads. The test then runs the real function instead of the stand-in. Depending on the test, it fails or, worse, passes without testing what it claims. Every move must therefore audit these swaps (question Q3).

## F136 · VERIFIED · JSON logs record the Python module name

The two JSON log sinks use `serialize=True` ([sinks](../../src/logging_utils.py#L193)). Loguru 0.7.3 then writes the full record, including the module name, file, function and line. Command run in an isolated process with dotenv loading disabled:

```powershell
$env:PYTHON_DOTENV_DISABLED=1; uv run --locked python -c "import io, json; from loguru import logger; logger.remove(); b=io.StringIO(); logger.add(b, serialize=True, format='{message}'); logger.info('x'); r=json.loads(b.getvalue())['record']; print(sorted(r))"
```

```text
['elapsed', 'exception', 'extra', 'file', 'function', 'level', 'line', 'message', 'module', 'name', 'process', 'thread', 'time']
```

The text log format has no module field: `"{extra[timestamp_iso]} | {level:<8} | {extra[event]} | " …` ([format](../../src/logging_utils.py#L161)). Moving a module therefore changes `application.jsonl` and `database/database_events.jsonl`, but not `application.log` (question Q4).

## F137 · VERIFIED · Old import paths already have a safety test

Earlier moves left re-export modules behind: `src/web/pages/*`, `src/orchestration/browser_session.py` and `src/pipelines/solve_slider.py`. A contract test runs in a fresh Python process and checks that each old name *is* the same object as the new one:

```python
# tests/contract/test_import_initialization.py:L105-L107
legacy = getattr(importlib.import_module("src.web.pages." + filename), name)
assert legacy is getattr(pages, name) is getattr(legacy_pages, name) is getattr(browser, name)
```

Every phase below extends this pattern. A new test is added for each old path, and the existing test stays as it is. [Contract test](../../tests/contract/test_import_initialization.py#L91)

## F138 · CONTRADICTED · The earlier “How to check” commands do not run

The previous revision of this plan used `uv run --locked rg …`. On this machine `rg` is not a program that `uv run` can start:

```text
$ uv run --locked rg --version
error: Failed to spawn: `rg`
  Caused by: program not found
```

The [How to check](#how-to-check) section now uses PowerShell `Select-String`, which ships with Windows.

## F139 · CONTRADICTED · The mypy strict list the rules describe does not exist

The agent rules (§5) say that the strict list is the `[[tool.mypy.overrides]]` block with the strict flags. `pyproject.toml` has one override, which only covers `psycopg2`:

```toml
# pyproject.toml:L31-L33
[[tool.mypy.overrides]]
module = ["psycopg2", "psycopg2.*"]
follow_untyped_imports = true
```

`Select-String -Path pyproject.toml -Pattern 'strict|disallow'` finds no match. New modules created by a move therefore have no strict list to join yet (question Q9).

## Phases, proof and rollback

Every phase follows the [per-move checklist](#per-move-checklist), runs on its own branch and ends with its own activity doc. A phase moves code. It never changes what the code does.

| Phase | Work and documentation | Done when | How to undo |
| --- | --- | --- | --- |
| **R0 · Agree on names and the map** | Answer Q1–Q4. Write a glossary of domain terms (`NIK`, `KUOTA`, page titles) in `shared/`’s README, plus a one-page “where to look” guide for *today’s* layout. Documentation only. | A new reader can find a button, a skip decision, a confirmed result, a database write and the final report file using only the guide. Every link opens the named symbol. | Edit the docs. |
| **R1 · Add the safety rails** | Review allowed imports and list existing violations (Q14). Keep Ruff and mypy. Create the empty mypy strict list (Q9). Apply the test rule from Q13 to the agent rules. Record the golden master at the starting revision. No file moves. | The agreed gate passes. Phase review records any forbidden imports. Golden master recorded twice, with the two runs identical. | Revert the test and the `pyproject.toml` commit. |
| **R2 · Move the shared helpers** | Move settings, logging, privacy and path helpers to `shared/`. Leave a re-export at each old path. | Gate and golden master pass. Old and new paths return the same object (new contract test). `application.log` is byte-identical. | Revert the move commit. |
| **R3 · Make the puzzle service one folder** | Move `vision/`, `pipelines/slider/` and `puzzle_service.py` into `puzzle_solving/`. Keep the current OpenCV code, flags and NumPy types exactly as they are. The workflow keeps calling the same functions. | Gate and golden master pass. Puzzle tests pass with the same results. Saved puzzle diagnostics have the same names and bytes. | Revert the move commit. |
| **R4 · Make the database service independent** | Move `infrastructure/database/` to `database/`. First remove the sync’s import of the reporter by passing the needed function in. That is a design change, so it gets its own commit and proof. | The database sync imports nothing from reporting. Database rows, receipts and recovery records match the golden master after success, failure and restart. | Revert each commit separately. |
| **R5 · Make the report service one folder** | Move `web/reporter.py` and `infrastructure/reporting/` to `reporting/`. Keep the order stage → CSV → JSONL → queue database ([F124](#f124--verified--the-order-of-saving-a-result-matters)). | Report bytes, database rows and receipts match. Interrupting between the two files, between files and database, and after a commit gives the same state as before. | Revert the move commit. |
| **R6 · Make the web page automation one folder** | Move the outcome models that page objects import to a neutral place (`shared/` or `business_workflow/outcomes`, decided in R0). Then move the browser session, pages, dialogs, puzzle capture and diagnostics to `web_automation/`. | `web_automation` imports no other service. Page and precheck tests pass. In the local dummy shop, the ready, skip and stop outcomes match the golden master. No new click, wait or retry. | Revert the move commits. Old paths keep working. |
| **R7 · Make the business workflow one folder** | Move the customer loop, prechecks, account runner, session recovery and rate limiting to `business_workflow/`. Add `service_interfaces.py` with typing Protocols that describe what the workflow uses from the other services. They are descriptions only, and no call changes. | Golden master covers ordinary sale, optional onboarding, skip, stock stop and unknown confirmation. The ordered outcomes, attempts and quota changes match. An uncertain result never causes a second sale attempt. | Revert the move commit. Never replay a sale to test rollback. |
| **R8 · Split the largest modules** | One module per iteration, starting with `dashboard_page.py` (F132). Split by job (for example one module per dashboard area), with no logic change. | Same as the phase that moved the module. Each new module has a docstring and joins the strict list. | Revert that one split. |
| **R9 · Prepare the read-only API boundary** | After Q7: one operation, “read a finished run’s totals”, as a plain Python function in `api/` with a typed response model. It reuses the existing report readers. No server and no new dependency. Document the fields, missing-run and partial-run behavior and the privacy rule. | Dummy examples match existing summary counts, handle missing and partial runs, and show only approved fields. CLI output and golden files are unchanged. | Delete `api/`. Nothing else uses it. |
| **R10 · Remove old import paths** | Only after Q5 and Q11: remove the re-export modules whose callers are all updated. One path per commit. | No caller left in the repo or in the list from Q5. Gate and golden master pass. | Restore the re-export module. |

**After this plan.** Serving the API over HTTP, a GUI and any command that starts or recovers a sale are separate features. Each needs its own plan, with access control, duplicate-request handling and dummy-shop safety tests.

### How the earlier S1–S6 phases map to the new phases

| Earlier phase | Now |
| --- | --- |
| S1 · Draw the map | R0 |
| S2 · Make the browser boundary clear | R6 |
| S3 · Name the sales and puzzle boundaries | R3 and R7 |
| S4 · Put the reporter where readers expect it | R5 |
| S5 · Prepare a read-only API boundary | R9 |
| S6 · Future API and GUI | After this plan |

### Per-move checklist

1. Before the move, run the gate and the golden master on the starting revision. If anything fails, stop and report it (agent rules §3).
2. Move with `git mv` in a commit that changes nothing else, so `git log --follow` keeps the history.
3. Leave a re-export module at the old path. Its docstring names the new path and Phase R10.
4. Update the imports in `src/` and in entry points. Update test imports only under the rule agreed in Q3.
5. List every `monkeypatch.setattr` on the moved module and confirm that each one now targets the module the code reads ([F135](#f135--verified--tests-swap-out-names-on-the-module-that-uses-them)).
6. Add a contract test that checks old path `is` new path ([F137](#f137--verified--old-import-paths-already-have-a-safety-test)).
7. Give every module a docstring that says what it is for and who calls it. Add new modules to the strict list.
8. Run the gate in order, then the golden master. Business reports and `application.log` must be byte-identical. JSON log changes are limited to what Q4 allows.
9. Write the phase doc: moved paths, test import changes, checks, golden-master result, remaining callers and rollback.

### Risks

| Risk | Evidence | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| A test silently stops replacing a function after a move. | F135 | High | High | Checklist step 5, and the rule from Q3. |
| An import cycle or a changed import order changes startup behavior. | F134 | Medium | High | Move neutral models first (R6), and add the fresh-process import test. Stop on any cycle. |
| JSON log records change module names. | F136 | Certain | Low | Owner rule from Q4. Byte-compare the text log. |
| An outside script or scheduled task uses an old path. | Q5 open | Unknown | Medium | Keep re-exports until R10. |
| A move and a logic change get mixed in one commit, so the golden master cannot show which one broke. | Agent rules §7 | Medium | High | One concern per commit. Splits happen only in R8. |
| A new layer of interfaces makes the code harder to read, not easier. | — | Medium | Medium | Protocols only in R7, only for calls that exist today, each with a docstring. |
| The API grows into a way to start sales without safety tests. | Q7 | Low | High | API stays read-only in this plan, and the allowed-imports table forbids `api` → `web_automation`. |

## How to check

Revision `741166c`, Python 3.14.2, loguru 0.7.3, Windows PowerShell 5.1. From the project root:

```powershell
git rev-parse --short HEAD
git log --oneline db5e95a..HEAD -- src main.py | Measure-Object -Line | Select-Object -ExpandProperty Lines
Select-String -Path main.py -Pattern 'browser_session_factory=BrowserSession|transaction_processor_factory=TransactionProcessor|report_syncer=DatabaseReportSyncer' | ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
Select-String -Path src/web/reporter.py -Pattern 'self.file_writer.append_row\(row\)|self._queue_row_for_batch_sync\(row\)' | ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
Get-ChildItem src/infrastructure -Recurse -Filter *.py | Select-String -Pattern '^from src\.(application|web)' | ForEach-Object { "$($_.Filename):$($_.LineNumber)" }
Get-ChildItem tests -Recurse -Filter *.py | Select-String -Pattern 'monkeypatch\.setattr\(\s*[a-z_]+' -AllMatches | ForEach-Object { $_.Matches.Value } | Group-Object | Sort-Object Count -Descending | Select-Object -First 6 | ForEach-Object { "$($_.Count) $($_.Name)" }
"strict matches: " + (Select-String -Path pyproject.toml -Pattern 'strict|disallow' | Measure-Object).Count
```

Output of the run for this plan:

```text
741166c
0
115: browser_session_factory=BrowserSession,
116: transaction_processor_factory=TransactionProcessor,
117: report_syncer=DatabaseReportSyncer(),
1139: self.file_writer.append_row(row)
1150: self._queue_row_for_batch_sync(row)
base_page.py:6
cek_penjualan_page.py:6
customer_update_page.py:7
report_syncer.py:17
31 monkeypatch.setattr(taskbot_main
19 monkeypatch.setattr(reporter
19 monkeypatch.setattr(transaction_processor
10 monkeypatch.setattr(export
8 monkeypatch.setattr(reporting
6 monkeypatch.setattr(target
strict matches: 0
```

The `0` on the second line means no file under `src/` or `main.py` changed since `db5e95a`, so the line links in F123–F124 still hold. Line counts in F132 and the imports in F133 came from `wc -l` and `grep` in Git Bash at the same revision. The gate and the golden master were **NOT RUN**: this task changes Markdown only, and no code moved.

## Open items

- Q13–Q14 gate Phase R1. Q15 gates Phase R10. Phase R0 has no open question.
- **UNVERIFIED:** whether any tool outside this checkout imports TaskBot modules (Q5). This can be checked by asking the owner and searching any scheduled tasks on the operator machine.
- Record the import-boundary review in R1 (Q14).
