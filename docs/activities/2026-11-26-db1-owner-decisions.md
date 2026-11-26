# DB1 customer queues and recovery evidence

Six fictional customer queues now have exact-order checks in SQLite and PostgreSQL. The owner approved the rules. Acceptance of these example queues and a replay by another developer remain open. [Selection decisions](../plans/2026-11-26-plan-owner-questions-and-answers.md#database-plan-questions) · [SQL example](../../db_query/db1-customer-queue-example.sql) · [Pytest assertions](../../tests/contract/test_db1_customer_queue_example.py#L15)

## How to check

Use an isolated checkout containing the DB1 SQL and test, with the locked dependencies and no real dotenv files. For a replay without a database server, run only `test_sqlite_customer_queues`. For both tests, configure libpq authentication for an existing disposable database named `taskbot_quota_test_*` on the local `taskbot_phase1` cluster. The test uses the same host, port and opt-in variable as the [existing PostgreSQL tests](../../tests/contract/test_quota_receipts_postgres.py#L20).

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:TASKBOT_QUOTA_TEST_DB = 'taskbot_quota_test_000d348aa867' # Substitute your local test database.
Write-Output "DB host=127.0.0.1 port=55432 dbname=$env:TASKBOT_QUOTA_TEST_DB; SQLite=:memory:"
uv run --locked --no-sync pytest -v tests/contract/test_db1_customer_queue_example.py
```

Observed on the isolated checkout at base `6a7a97b` with the DB1 changes, Python 3.14.2 and pytest 9.0.2:

```text
tests/contract/test_db1_customer_queue_example.py::test_sqlite_customer_queues PASSED [ 50%]
tests/contract/test_db1_customer_queue_example.py::test_postgres_customer_queues PASSED [100%]
```

## F155 · VERIFIED · The dummy queues follow the approved priority order

Markdown checks: `npm.cmd exec --offline -- markdownlint-cli2 docs/activities/2026-11-26-db1-owner-decisions.md "docs/plans/*.md"` and `npm.cmd run --silent lint:md` both reported `Summary: 0 issues in 0 files`.

C is new. A ran out of stock yesterday. B reached the registration request limit yesterday. D reached maximum quota yesterday and waits for the new month. E previously succeeded and F was untouched in the last run. E and F have the same update day, so their fictional identifiers break the tie. Restart assumes a verified final outcome for C. The outside example assumes the inside queue is exhausted and the monthly share permits G. These are inputs to the paper example.

Allocation counts **customers**. For example, six inside customers split three per operator and four outside customers split two per operator. A shared number goes to review. Moving it requires operator and owner approval. The monthly outside share counts **confirmed sales** per operator. The daily stop counts **stock units** per operator. Those three quantities serve different decisions.

## F156 · VERIFIED · Recovery already records an outcome for each delivery event

The journal records an attempt with `INSERT INTO events(id, ready, source, payload)` and a confirmation with `UPDATE events SET ready=2`. The database writer records the event ID and terminal status with `ON CONFLICT (event_id) DO NOTHING` and checks the identity on replay. These references establish local code behavior. A shop-side receipt remains necessary to settle an uncertain remote outcome. [Journal start and confirmation](../../src/infrastructure/database/quota_journal.py#L76) · [Database delivery receipt](../../src/infrastructure/database/operator_store.py#L762)

## F157 · VERIFIED · The day and month boundaries give the expected queues on both engines

In the example, C has an empty status and no sale. A ran out of stock, B reached the registration limit, and D reached the monthly maximum on October 30. E previously completed a sale. F was untouched in the last run. E and F have identical update dates. The input puts F before E so the expected E–F order checks the final tie-breaker. [Fictional rows](../../db_query/db1-customer-queue-example.sql#L3) · [Order and eligibility](../../db_query/db1-customer-queue-example.sql#L21)

| Scenario | Expected queue | What the owner can check |
| --- | --- | --- |
| October 30, same day | C E F | A and B must wait until tomorrow. D waits for the next month. |
| October 31, ordinary day | C A B E F | C is new. A and B are now eligible, in that order. |
| November 2, first processing day | C A B D E F | D follows the daily retries even when the first processing day falls after the 1st. |
| November 3, later processing day | C A B E F D | D returns to ordinary oldest-first order. E and F were updated before D. |
| November 2, restart after C | A B D E F | The example supplies a confirmed final outcome for C today. |
| Outside area eligible | G | The operator has exhausted eligible inside customers and may choose outside under the monthly share rule. |

Each scenario starts independently with the stated inputs. Calendar dates are fixed WIB dates. The outside decision and C’s final outcome are inputs. The test makes no sale and reads only fictional rows. SQLite 3.50.4 and PostgreSQL 18.4 both passed the same six assertions at base `6a7a97b` plus these edits. [Scenario inputs](../../db_query/db1-customer-queue-example.sql#L11) · [Expected queues](../../tests/contract/test_db1_customer_queue_example.py#L15)

**Deliberate differences from F120.** The saved query gives an old monthly maximum priority over yesterday’s stock retry and orders peers by historical maximum quota, then update time. DB1 gives new customers, stock retries and registration retries precedence. Within each group the oldest update wins, then the customer key breaks an exact tie. Same-day retries wait. These changes describe the example only. [Earlier query priorities](../plans/2026-11-25-plan-database-customer-selection.md#f120--verified--eligibility-comes-before-priority) · [Fixture ordering](../../db_query/db1-customer-queue-example.sql#L24)

**Rule glossary.** Customer allocation counts people per operator and area. Outside share counts confirmed outside sales divided by all confirmed sales for that operator in the WIB month. Daily stock counts confirmed units per operator. `KUOTA` counts a customer’s quota used this month. `MAX_KUOTA` records the historical high. A final outcome is a confirmed terminal result for the customer that day. An uncertain outcome requires reconciliation. [Owner decisions Q14–Q23](../plans/2026-11-26-plan-owner-questions-and-answers.md#database-plan-questions)

**Local clocks.** `(Get-TimeZone).Id` returned `SE Asia Standard Time` on the development machine. On the disposable PostgreSQL database, `select current_setting('cluster_name'), current_database(), current_setting('TimeZone')` returned `taskbot_phase1|taskbot_quota_test_000d348aa867|Asia/Jakarta`. The test also asserts `("taskbot_phase1", database, "on")` before executing the example in a read-only transaction. [Session check](../../tests/contract/test_db1_customer_queue_example.py#L65)

**Tool checks.** The test module passed `uv run --locked --no-sync ruff check tests/contract/test_db1_customer_queue_example.py` (`All checks passed!`) and `uv run --locked --no-sync ruff format --check tests/contract/test_db1_customer_queue_example.py` (`1 file already formatted`). The Markdown checks used markdownlint-cli2 0.24.2:

```powershell
npm.cmd exec --offline -- markdownlint-cli2 docs/activities/2026-11-26-db1-owner-decisions.md docs/plans/2026-11-25-plan-database-customer-selection.md docs/plans/2026-11-23-plan-modernization.md
npm.cmd run --silent lint:md
```

Both reported `Summary: 0 issues in 0 files`.

## Open items

- **PARTIAL.** The exact queues passed on the development machine. The owner’s review, another developer’s replay, the operational machine and database clock settings, and a running-shop restart remain unverified.
- **UNVERIFIED.** The owner observed completion on the page. The timing of server acceptance and the outcome of the individual sale remain unknown. Use the attempt, terminal report and matching Rekap Penjualan entry for reconciliation.
- **Commit gate stopped.** Before DB1 edits, `uv run --locked ruff format --check .` (Ruff 0.17.6) reported `2 files would be reformatted, 164 files already formatted`. On the DB1 worktree it reported `2 files would be reformatted, 165 files already formatted`. Both findings were existing Python examples in the quota recovery activity and project structure plan. Remaining commit gates and the whole-app golden master were **NOT RUN** after the first failure. The focused DB1 test ran separately.
