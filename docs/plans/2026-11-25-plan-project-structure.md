# Project structure plan · Where should I look?

- **First step.** Give the next developer a one-page map. Someone looking for a button, a sale rule or a missing report should be able to find the right file before we move anything.
- **Suggested layout.** Keep browser pages, sale decisions, puzzle results, database writes and reports easy to find in one Python project. Use the existing folders where they already describe their job.
- **Later.** Prepare a way to read a run summary from either the CLI or a future API. Build a server or GUI only after choosing its first user and task.
- **Open.** Agree on names, supported imports and commands, report readers, and what a future API may show. S1–S5 are proposed steps with behavior preserved. S6 is a separate feature decision. [Database plan](2026-11-25-plan-database-customer-selection.md) · [Modernization closeout](2026-11-23-plan-modernization.md)

## Questions and answers

1. **S-Q1. Which words make the folders easiest to find?** Suggested map labels: “Browser pages”, “Sales workflow”, “Puzzle result”, “Database and quota”, “Reports”, “Run from CLI” and, later, “API”. Keep familiar names such as NIK and KUOTA in field descriptions. **A. Open.** As a reader check, find where a button lives, where a skip is decided and where one customer’s result is saved.
2. **S-Q2. Which old entry points do people still use?** Does anyone import modules directly, start a scheduled command, run a recovery or session export command, or keep a tool outside this checkout? **A. Open.** Suggest retaining old commands and import paths while collecting actual callers. A function without an internal caller may be a manual entry point.
3. **S-Q3. Which files are read outside TaskBot?** Who uses per-customer CSV/JSONL, run summaries, session exports, diagnostics, rotated logs or browser profiles? Are exact paths or bytes required by other tools? **A. Open.** Suggest keeping the existing outputs and privacy rules throughout the moves. Record an owner and a sample use before retiring any format.
4. **S-Q4. What is the first screen or API call for?** Read an existing run, preview the next-customer list, start a run or recover one? Who may see totals, individual results or customer numbers? What if a user clicks Start twice? **A. Open.** Suggest read-only totals for a completed run first. Starting a sale needs separate authorization, concurrency and restart decisions.
5. **S-Q5. How far should each iteration go?** Is a one-page map enough where a folder already reads clearly? Who will try the navigation questions after each move? **A. Open.** Suggest one responsibility per change and a short reader check. Give an import a replacement and support period before removing it.
6. **S-Q6. Which work goes first?** Is easier navigation or replacing the manual list the immediate priority? **A. Open.** S1 and DB1 can proceed independently. Keep a folder move separate from changing the database schema, the customer list or when a sale is counted.

## F123 · VERIFIED · The CLI already connects the pieces

In `_build_account_runner`, the CLI passes `browser_session_factory=BrowserSession`, `transaction_processor_factory=TransactionProcessor` and `report_syncer=DatabaseReportSyncer()`. The account runner receives these objects, and `run_account` passes that runner to `process_account`. This gives us a place to change an implementation without giving each caller its own setup code. [CLI wiring](../../main.py#L101) · [CLI delegation](../../main.py#L123) · [Runner](../../src/application/services/account_runner.py#L20)

| If you want to know… | Open this first | What the source shows |
| --- | --- | --- |
| Where does the app find and use a page? | [Browser session](../../src/infrastructure/browser/playwright_session.py#L24) and [dashboard page](../../src/infrastructure/browser/page_objects/dashboard_page.py#L136) | The browser has its own session class. The old web dashboard module already re-exports the page class. [Old import](../../src/web/pages/dashboard.py#L1) |
| Who gets processed, skipped or stopped? | [Customer loop](../../src/orchestration/transaction_processor.py#L95) and [precheck decisions](../../src/application/services/transaction_prechecks.py#L167) | The loop takes the configured customers in order. A stock exception breaks the loop. Prechecks distinguish ready, expired session and refusal. |
| What does the puzzle stage return? What makes a sale count? | [Puzzle result](../../src/application/services/puzzle_service.py#L13) and [sale outcome](../../src/application/models/transaction_outcome.py#L13) | The puzzle result carries a solved flag and attempt counts. The sale check separately requires `self.status == "completed" and bool(self.evidence.strip())`. Someone changing reporting needs the second rule. |
| Where do quota and recovery live? | [Operator store](../../src/infrastructure/database/operator_store.py#L300), [DB sync](../../src/infrastructure/database/report_syncer.py#L22) and [quota journal](../../src/infrastructure/database/quota_journal.py#L33) | The store constructs a quota delta, the syncer manages report-row delivery, and the journal has a destination/operator context. The operator SQL already has its own module. [Quota arithmetic](../../src/infrastructure/database/_operator_sql.py#L93) |
| Who saves the customer result? | [Reporter](../../src/web/reporter.py#L1134) and [file writer](../../src/infrastructure/reporting/file_writer.py#L60) | The reporter stages quota delivery, calls the file writer and queues the DB sync. The writer appends CSV and then JSONL. Moving the reporter changes several callers even though its folder says “web”. |

## F124 · VERIFIED · The order of saving a result matters

In the reporter, `self.file_writer.append_row(row)` precedes `self._queue_row_for_batch_sync(row)`. A named contract test covers persistence, sync and summary order. A separate test covers an unconfirmed sale and prevents retrying it. These are starting checks for any move near those boundaries. [Write and queue](../../src/web/reporter.py#L1134) · [Persistence contract](../../tests/contract/test_reporting_and_main.py#L65) · [Unconfirmed-sale contract](../../tests/contract/test_transaction_processor.py#L855)

## Proposed navigation map

These are suggested destinations. A new path becomes real only in its approved phase.

```text
main.py                              Start from the CLI and connect the pieces
src/application/sales/               Run an operator, process one customer, decide outcomes
src/infrastructure/browser/          Open a session, observe pages and act on named DOM elements
src/application/puzzle/              Give the sales workflow the existing puzzle-stage result
src/infrastructure/database/         Read/write PostgreSQL, apply quota rules and recover delivery
src/infrastructure/reporting/        Write and read report files and summaries
src/infrastructure/config/           Read settings and today’s configured customer list
src/interfaces/api/                  Possible later entry point, only when an API is approved
```

Keep three distinctions visible in the map. A browser page reports what it sees. The sales workflow chooses whether to continue, skip, stop or record an uncertain outcome. The reporter and DB store make the result durable in their existing order. Document puzzle inputs and result fields at the boundary. Keep the current image-processing implementation in place during a folder move. [Precheck decisions](../../src/application/services/transaction_prechecks.py#L167) · [Puzzle result](../../src/application/services/puzzle_service.py#L13) · [Persistence order](../../src/web/reporter.py#L1134)

**Options.** A map alone has the least risk and might solve the reader’s problem. Moving one confusing responsibility at a time improves names while retaining the current CLI and working modules. Splitting into independent network services now would add deployment, failure and recovery decisions before we know which API operation is needed. Recommend starting with the map and using the second option wherever a reader still gets lost (F123–F124, S-Q1–Q5).

## Phases, proof and rollback

| Phase | Proposed work and documentation | Accept it when | How to undo or stop |
| --- | --- | --- | --- |
| **S1 · Draw the map** | Make a one-page “where to look” guide. Include the CLI entry, links to actual files, who calls whom, optional branches, and where to look after a failure. Mark manual utilities, compatibility imports and unknown callers separately. | A reader can find a button, business skip, confirmed result, DB write and final file using only the guide. Every link opens the named symbol. No source move. | Correct the map using reader feedback. |
| **S2 · Make the browser boundary clear** | Start with one page that already has a compatibility import. Keep selectors and browser timing together. Keep business outcomes in their present workflow. Document old path → current path and audit callers and test patch paths. | Both import paths return the same object. Existing page and precheck tests pass. Confirm ready, skip and stop outcomes against the local dummy shop golden. No new click, retry or timing change. | Revert the one move and its import wiring. Keep the old path usable. |
| **S3 · Name the sales and puzzle boundaries** | Move one workflow responsibility per iteration, beginning with the customer loop. Then document the existing puzzle result as a separate input to the sale decision. Keep branch order, counts and exception handling. | Check ordinary sale, optional onboarding, skip, stock stop and unknown confirmation. Compare the ordered customer outcomes, attempts and quota deltas. An uncertain result never causes a second sale attempt. Use the existing contract and the Phase 1 golden. | Revert the individual move. Do not replay a sale to test rollback. |
| **S4 · Put the reporter where readers expect it** | Move reporting coordination behind its old import in a dedicated change, leaving file writing and DB delivery in their existing modules. Document the order of stage → write CSV/JSONL → queue DB and the recovery path. | Compare golden report bytes, DB rows and receipts. Interrupt between the two files, between files and DB, and after a DB commit. Check the exact exception and recovery state. Recheck old imports and output paths. | Revert the move and its import changes. Keep existing recovery records readable. |
| **S5 · Prepare a read-only API boundary** | After S-Q4, define the smallest reusable operation for reading a completed run summary. Specify fields, source, missing-run and partial-run behavior, privacy and who may call it. Reuse existing report readers where possible. Document CLI → reader and future UI → API → same reader. | Dummy examples match existing summary counts, handle missing/partial files and reveal only approved fields. CLI output and golden files remain identical. No server, network dependency or database switch is needed for this step. | Remove the new internal reader if unused. Leave report writers and CLI intact. |
| **S6 · Future API and GUI** | Only after approval, expose the agreed read-only operation and build a screen around it. Treat previewing customers or starting/recovering runs as separate capabilities. Decide access control, duplicate requests and run ownership before accepting commands. | Owner can complete the named task without opening the project. Check permissions, field visibility and failure messages. A read has no sale or quota side effects. Any later command requires its own dummy-shop safety test. | Disable the new interface. Keep the existing CLI and data recoverable. |

For S2–S5, run the locked format, lint, type and test gates in order, then the Phase 1 golden for code changes. Keep a dated record of moved paths, checks, output comparisons, remaining callers and rollback. Record suspected dead code as “no internal caller found” until searches, imports, CLI usage and the owner’s answer support removal. Removing an entry point or changing a report format needs its own decision. [Project gates](../../AGENTS.md) · [Phase 1 acceptance](../activities/2026-11-23-phase-1-behavior-baseline.md#12-phase-1-acceptance)

## How to check

Source revision `db5e95a`, Python 3.14.2. From the project root:

```powershell
uv run --locked rg -n "browser_session_factory=BrowserSession|transaction_processor_factory=TransactionProcessor|report_syncer=DatabaseReportSyncer" main.py
uv run --locked rg -n "self.file_writer.append_row\(row\)|self._queue_row_for_batch_sync\(row\)" src/web/reporter.py
uv run --locked rg -n "def test_terminal_row_persists_then_syncs_before_summary|def test_unconfirmed_sale_never_completes_or_retries" tests/contract
```

Relevant output, trimmed:

```text
115:        browser_session_factory=BrowserSession,
116:        transaction_processor_factory=TransactionProcessor,
117:        report_syncer=DatabaseReportSyncer(),
1139:            self.file_writer.append_row(row)
1150:            self._queue_row_for_batch_sync(row)
tests/contract\test_reporting_and_main.py:65:def test_terminal_row_persists_then_syncs_before_summary(
tests/contract\test_transaction_processor.py:855:def test_unconfirmed_sale_never_completes_or_retries(confirmed_sale_processor, outcome):
```

The documentation check used an isolated copy without operational dotenv files and the separate PostgreSQL 18 test instance. Recorded results for both plans:

| Command | Relevant output |
| --- | --- |
| `uv run --locked ruff format --check .` | `158 files already formatted` |
| `uv run --locked ruff check .` | `All checks passed!` |
| `uv run --locked mypy .` | `Success: no issues found in 144 source files` |
| `uv run --locked pytest` | `1450 passed` |

Tool versions were Ruff 0.17.6, mypy 2.4.1 and pytest 9.0.2. Golden comparison **NOT RUN** for this planning task because the changes are Markdown only. New module moves, a server and UI were **NOT RUN**. They remain proposals for later review.

## Open items

Answer S-Q1 and S-Q2 to start the map. S-Q3–Q6 cover later readers, interfaces, work order and approvals.
