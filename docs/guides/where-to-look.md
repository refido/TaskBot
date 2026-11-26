# Where to look in today’s code

- **What this is.** A one-page map of TaskBot’s code *as it is today*, before any folder moves. It answers five questions a new reader asks first, then follows one customer from start to finish.
- **How to use it.** Start from a question in the first table and open the first link. Every code link opens the line where the named symbol is. Shop and owner words are explained in the [glossary](glossary.md).
- **When it changes.** Each move phase (R2–R7) changes these paths. The phase that moves a module updates this guide ([project structure plan](../plans/2026-11-25-plan-project-structure.md#phases-proof-and-rollback)).
- **Status.** Written in Phase R0 on 2026-11-26 at revision `6a7a97b`. [Activity doc](../activities/2026-11-26-structure-r0-glossary-and-code-map.md)

## Five questions and where to start

| You want to find… | Open this first | Then follow |
| --- | --- | --- |
| **A button.** Where is CEK PESANAN clicked? | [`Penjualan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L55), the sale page | The locator is [`CEK PESANAN`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L58) and the click is [`cek_pesanan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L93). Every page clicks through [`click_button_and_wait`](../../src/infrastructure/browser/page_objects/base_page.py#L60). Other buttons are in the same folder: one module per page or pop-up. Shop page texts are listed in the [glossary](glossary.md#shop-page-texts). |
| **A skip decision.** Who decides to skip a customer? | [`handle_pre_checks`](../../src/application/services/transaction_prechecks.py#L137) | It returns a [`PrecheckAction`](../../src/application/models/customer_workflow.py#L10). The customer loop acts on it at [`PrecheckAction.SKIP`](../../src/orchestration/transaction_processor.py#L179). Each blocker has its own handler, for example [`_handle_fraud`](../../src/application/services/transaction_prechecks.py#L680), which calls [`self.reporter.skip`](../../src/application/services/transaction_prechecks.py#L689). Maximum quota and empty stock are checked later, on the sale page: [`check_max_kuota`](../../src/application/services/transaction_prechecks.py#L1052) · [`check_zero_stock`](../../src/application/services/transaction_prechecks.py#L1064). |
| **A confirmed result.** When does a sale count? | [`wait_for_transaction_outcome`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L59) | Only a visible [`KEMBALI KE HALAMAN UTAMA`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L87) gives `completed` with evidence. [`success_confirmed`](../../src/application/models/transaction_outcome.py#L18) requires both. The loop checks it at [`not outcome.success_confirmed`](../../src/orchestration/transaction_processor.py#L424) and only then calls [`self.reporter.complete`](../../src/orchestration/transaction_processor.py#L464). |
| **A database write.** Where is the operator table changed? | [`sync_report_payloads`](../../src/infrastructure/database/operator_store.py#L577) | One transaction per call: [`with db_connection, db_connection.cursor() as cursor`](../../src/infrastructure/database/operator_store.py#L625) commits on success and rolls back on error. The row is built by [`from_report_payload`](../../src/infrastructure/database/operator_store.py#L279) and written by [`upsert_record`](../../src/infrastructure/database/operator_store.py#L851) with the SQL from [`upsert_sql`](../../src/infrastructure/database/_operator_sql.py#L76). The quota arithmetic is [`next_kuota`](../../src/infrastructure/database/_operator_sql.py#L93). |
| **The final report file.** What is written last? | [`_write_run_meta`](../../main.py#L144) | It writes [`run_meta.json`](../../main.py#L196) for the whole run, at the end of [`main`](../../main.py#L282). Per operator, [`write_files`](../../src/web/reporter.py#L653) writes [`items_snapshot.json`](../../src/web/reporter.py#L965) and `analytics.json`. The per-customer rows are appended earlier, one at a time, to [`items.csv`](../../src/web/reporter.py#L962) and [`items.jsonl`](../../src/web/reporter.py#L963). |

## One customer, from start to finish

1. **Start.** [`main`](../../main.py#L282) reads the settings and builds one runner per operator in [`_build_account_runner`](../../main.py#L101). The runners run side by side through [`process_accounts`](../../src/application/use_cases/process_account.py#L11).
2. **Open the browser and log in.** [`AccountRunner`](../../src/application/services/account_runner.py#L8) opens a [`BrowserSession`](../../src/infrastructure/browser/playwright_session.py#L189) and logs in with [`Login`](../../src/infrastructure/browser/page_objects/login_page.py#L7).
3. **Loop over the customer list.** [`process_all_niks`](../../src/orchestration/transaction_processor.py#L95) takes the configured customer numbers in order. Empty stock ends the loop for this operator: [`OutOfSellableStockError`](../../src/orchestration/transaction_processor.py#L100).
4. **Enter the customer number.** [`catat_penjualan`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L740) opens the sale page from the [`Dashboard`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L136).
5. **Prechecks.** [`resolve_customer_state`](../../src/application/services/transaction_prechecks.py#L384) reads what the page shows, and [`handle_pre_checks`](../../src/application/services/transaction_prechecks.py#L137) acts on it: customer type, consent, NIB reminder, the one allowed customer update, or a skip.
6. **Sale and puzzle.** The sale page [`Penjualan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L55) and the sale check page [`CekPenjualan`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L27) submit the sale. [`PuzzleService.solve`](../../src/application/services/puzzle_service.py#L58) runs the image matching in [`PuzzleSolver`](../../src/vision/puzzle_solver.py#L82) and the slider drag in [`solve_slider_with_puzzle`](../../src/pipelines/slider/solver.py#L191).
7. **Result.** The sale check page reports the outcome (see “A confirmed result” above). A lost session goes to [`SessionRecoveryService`](../../src/application/services/session_recovery.py#L12).
8. **Save the result.** [`_record_row`](../../src/web/reporter.py#L1134) keeps a fixed order: stage the quota journal, then [`self.file_writer.append_row(row)`](../../src/web/reporter.py#L1139) (CSV, then JSONL, see [`append_row`](../../src/infrastructure/reporting/file_writer.py#L60)), then [`self._queue_row_for_batch_sync(row)`](../../src/web/reporter.py#L1150).
9. **Database.** With a batch size of [`_DATABASE_BATCH_SIZE = 1`](../../src/application/services/account_runner.py#L11), each queued row goes straight to [`DatabaseReportSyncer`](../../src/infrastructure/database/report_syncer.py#L22), which calls [`sync_report_payloads`](../../src/infrastructure/database/report_syncer.py#L160) (see “A database write” above).
10. **End of the run.** Each operator writes its snapshot files. Then `main` prints the run summary with [`_print_run_summary`](../../main.py#L216) and writes `run_meta.json`.

## Today’s folders

The right column is the service each folder moves to in the [target layout](../plans/2026-11-25-plan-project-structure.md#where-todays-modules-go).

| Folder or file | What lives there today | Moves to |
| --- | --- | --- |
| `main.py` | The command: settings, one runner per operator, the run summary and `run_meta.json`. | stays, gets thinner (`command_line`) |
| `src/config.py`, `src/infrastructure/config/` | Settings from the environment and the dotenv file: [`AppSettings`](../../src/infrastructure/config/settings.py#L21) · [`load_environment`](../../src/infrastructure/config/environment.py#L15) | `shared` |
| `src/logging_utils.py`, `src/privacy.py`, `src/path_utils.py` | Logging set-up ([`configure_logging`](../../src/logging_utils.py#L119)), customer-number masking, run-folder paths. | `shared` |
| `src/infrastructure/browser/` | Playwright session and one module per shop page or pop-up in `page_objects/`. | `web_automation` |
| `src/web/pages/` | 3-line re-exports of the page objects. Old import paths only. | `web_automation` (removed in R10) |
| `src/web/` (rest) | Not only web code: the reporter ([`TransactionReporter`](../../src/web/reporter.py#L95)), the rate limiters, the login-page check and the puzzle-image class [`Helpers`](../../src/web/helpers.py#L36). | `reporting`, `business_workflow`, `web_automation` |
| `src/orchestration/` | The customer loop ([`TransactionProcessor`](../../src/orchestration/transaction_processor.py#L52)). | `business_workflow` |
| `src/application/services/` | Prechecks, the account runner, session recovery and the puzzle step. | `business_workflow`, `puzzle_solving` |
| `src/application/models/`, `src/application/dto/` | Shared result types: customer states, precheck actions, sale outcome, run context. | neutral place, decided in R6 |
| `src/vision/`, `src/pipelines/` | Puzzle image matching (OpenCV, NumPy) and the slider drag. | `puzzle_solving` |
| `src/infrastructure/database/` | PostgreSQL: operator tables, quota SQL, report-to-database sync, quota journal, recovery command. | `database` |
| `src/infrastructure/reporting/` | File writer, analytics, classification, console summary. | `reporting` |
| `src/infrastructure/sessions/`, `user_sessions.py` | The separate user-session export tool. | `session_export` |
| `src/infrastructure/interaction_diagnostics.py` | Debug traces, screenshots and DOM logs, when `TASKBOT_INTERACTION_DEBUG=1`. | `web_automation` |
| `nik_parser.py`, `nik_region_mapping.json` | Decodes a customer number into region and birth date for the customer update: [`parse_nik`](../../nik_parser.py#L97) | not in the plan yet |
| `scripts/db_management.py` | Database command: `init` and `sync-report`. [`build_parser`](../../scripts/db_management.py#L15) | command stays, code to `database` |

## Commands

| Command | What it does | Code |
| --- | --- | --- |
| `uv run --locked main.py` | A full run for every configured operator. | [`main`](../../main.py#L282) |
| `uv run --locked python -m scripts.db_management init` | Creates the database and the operator tables. | [`main`](../../scripts/db_management.py#L42) |
| `uv run --locked python -m scripts.db_management sync-report <report>` | Sends a saved report into an operator table. | [`build_parser`](../../scripts/db_management.py#L15) |
| `uv run --locked python -m src.infrastructure.database.recover_quota <operator> list` | Quota recovery: `list`, `drain`, `confirmed`, `no-sale`. | [`main`](../../src/infrastructure/database/recover_quota.py#L23) |
| `uv run --locked python user_sessions.py` | Exports the user sessions. | [`main`](../../user_sessions.py#L17) |

Never run `inspect_env.py`: it opens the real `.env` (agent rules §4).

## Surprises for a new reader

- **`src/web/` is not the browser code.** The page objects live in `src/infrastructure/browser/page_objects/`. `src/web/` holds the reporter, the rate limiters and the puzzle-image class.
- **Two names for one browser session.** [`BrowserSession = PlaywrightSession`](../../src/infrastructure/browser/playwright_session.py#L189).
- **Class defaults are not the app’s settings.** For example, the skip limiter’s defaults are 5 skips in 60 seconds, but `main.py` sets [`max_skips=8`](../../main.py#L42).
- **Indonesian method names.** `catat_penjualan`, `cek_pesanan` and others are decoded in the [glossary](glossary.md#indonesian-words-in-todays-code-names).
- **Lazy imports.** `src/application/__init__.py` loads its services lazily to avoid an import cycle with the page objects ([structure plan F134](../plans/2026-11-25-plan-project-structure.md#f134--verified--imports-cross-the-layers-in-both-directions)). Do not change import order in passing.
