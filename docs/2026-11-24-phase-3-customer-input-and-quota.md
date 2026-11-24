# Phase 3 · Customer lists and quota writes

**Complete on November 24, 2026 for the local dummy shop and PostgreSQL 18 test instance.** The SQL move is commit `e8053ef`. Operators can keep using the same customer lists and reports. Seven paired runs produced identical business files and database records. F104–F107 give the evidence.

## F104 · VERIFIED · Where the customer list comes from

An operator's list comes from `NIK` or `NIK_<number>`. For example, `001, 001, ,002` gives the worker `001`, then `001` again, then `002`. The loader trims spaces, drops empty entries and keeps the remaining text as written. Its parsing expression is `tuple(nik.strip() for nik in raw_nik.split(",") if nik.strip())`. [Input parser](../src/infrastructure/config/settings.py#L194)

A populated numbered account takes precedence over the single-account settings. Numbered operators are ordered by numeric suffix, so operator 2 comes before 10. A configured operator can have an empty list. When all numbered slots are empty, the loader tries the single-account format. Each worker gets a list it can change independently. The two new tests cover duplicates, leading zeros, arbitrary text, empty slots, precedence and list independence. Both passed on the original code before the SQL move. [Account selection](../src/infrastructure/config/settings.py#L84) · [Per-worker list](../src/config.py#L74) · [New tests](../tests/unit/test_config.py#L11)

## F105 · VERIFIED · Where the quota SQL lives

The private module `_operator_sql.py` now builds the statements that create an operator table and insert or update a customer row. To find the quota rule, start at `upsert_sql()`. To find when a write commits or rolls back, start at `sync_report_payloads()` in the database manager. Its transaction still uses `with db_connection, db_connection.cursor() as cursor:`. The manager also owns the prior-row lookup, legacy migration and monthly reset. [Table definition](../src/infrastructure/database/_operator_sql.py#L34) · [Quota SQL](../src/infrastructure/database/_operator_sql.py#L76) · [Transaction](../src/infrastructure/database/operator_store.py#L625) · [Migration](../src/infrastructure/database/operator_store.py#L1048)

Existing calls to `OperatorDatabaseManager._create_table_sql()` and `_upsert_sql()` still work. We rendered the table creation, ordinary update and confirmed-receipt update statements for two table names using the PostgreSQL driver. All six SQL strings matched byte for byte. Both builders also raised the same exception type and message for an invalid table name. [Manager entry points](../src/infrastructure/database/operator_store.py#L1044) · [Quota entry point](../src/infrastructure/database/operator_store.py#L1136)

## F106 · VERIFIED · Tests and real PostgreSQL readback

The baseline was `c49ab097d0b1356bc981e007bdcf3db0d7e9a845`. Each full suite ran on a separate snapshot with operational dotenv files absent and a fresh disposable database. The launcher checked the local cluster name, data directory, port 55432 and PostgreSQL major version 18.

| Check | Observed result |
| --- | --- |
| Full suite on the baseline | `1445 passed in 89.37s (0:01:29)` |
| Two new input tests on the baseline application code | `2 passed in 0.06s` |
| Config, DB setup, sync, quota and failure tests on the candidate | `243 passed in 0.72s` |
| Full suite on the candidate, including the two new tests | `1447 passed in 68.74s (0:01:08)` |
| Project tools | Ruff printed `All checks passed!` and `151 files already formatted`. Mypy printed `Success: no issues found in 143 source files`. |

The legacy fixture started with an old `NAMA` column and a prior-month row with quota 4 and maximum 7. Migration preserved the operator name and backfilled the previous sale date into `LAST_TRANSACTION_TIME`. Monthly reset produced quota 0 and maximum 7. After a replay, a second receipt at the same time and an older receipt, the first operator ended at quota 3 and maximum 7. The second operator followed the ordinary write path. The comparison covered the full schema, primary key and every row at four points, all five sync summaries, and every field of all three receipts. The saved comparison printed `PASS: 6 rendered SQL statements, 2 invalid-name errors, 4 database snapshots, 5 sync summaries and 3 receipts matched`.

The suite also exercises a disabled database, a partially committed batch, and which exception wins when both the operation and cleanup fail. These are injected failure tests. The separate legacy comparison above used PostgreSQL. [Disabled DB](../tests/contract/test_db_sync_lifecycle.py#L201) · [Partial commit](../tests/contract/test_db_sync_lifecycle.py#L174) · [Close failure](../tests/contract/test_database_setup_lifecycle.py#L252) · [Rollback failure](../tests/contract/test_monthly_quota_lifecycle.py#L274)

## F107 · VERIFIED · Seven runs before and seven after

Each pair used the same dummy shop, customer order, report path, clock and starting data. A local fixture supplied the confirmation step. We fixed test receipt IDs in both snapshots so even the receipt keys could be compared. Hashes of all 143 candidate Python files matched the workspace after normalizing source line endings.

| Dummy case | Shop receipts | Database receipts before manual recovery | CSV / JSONL rows | App outcome |
| --- | ---: | ---: | --- | --- |
| One ordinary sale | 1 | 1 | 1 / 1 | `completed` |
| JSONL write fails once | 1 | 1 | 1 / 1 | `completed` |
| JSONL write keeps failing | 1 | 1 | 1 / 0 | `failed` |
| Database write fails once | 1 | 1 | 1 / 1 | `completed` |
| Database write keeps failing | 1 | 0 | 1 / 1 | `failed` |
| Customer updates, restart and skip | 5 | 5 | 6 / 6 | `completed_with_errors` |
| Eight ordinary routes | 8 | 8 | 8 / 8 | `completed` |

All 56 business files matched byte for byte. The comparator checked the complete file inventory, both operator tables' column definitions, primary keys and rows, and all fields in the database receipts. It also compared the shop ledger, exit codes, run outcomes, failure checkpoints and diagnostic events. The screenshot for the lasting JSONL failure showed the expected dummy dashboard. The raw verifier printed `RAW PASS` for all seven cases.

In the lasting DB failure, the dummy shop confirmed one sale while the database still showed quota 2, zero receipts and one pending local entry. Restoring access and running recovery produced quota 3, one receipt and zero pending entries. A second recovery gave the same result. **UNVERIFIED for daily sales.** These runs used loopback services and dummy customer records. [Recovery behavior and operator instructions](2026-11-23-quota-crash-recovery.md)

## Verification commands

The private evidence folder keeps the source snapshots, test logs, synthetic database readbacks and dummy-shop artifacts. The following are the commands for the runs recorded above. `suite.ps1` expands each full test command to `.venv\Scripts\python.exe -B -m pytest -q --basetemp <label>-tmp` in the named source snapshot. It creates a fresh fixture database and refuses to overwrite an existing suite label.

```powershell
$p = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/phase3-20261124-b78f7ce7'
& (Join-Path $p 'suite.ps1') reference before
& (Join-Path $p 'suite.ps1') current after
& (Join-Path $p 'legacy.ps1')
& (Join-Path $p 'pairs.ps1')
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe -B -m pytest -q tests/unit/test_config.py::test_numbered_input_preserves_each_operators_queue_and_ignores_single_input tests/unit/test_config.py::test_empty_numbered_slots_fall_back_to_the_single_input_list
.\.venv\Scripts\python.exe -B -m pytest -q tests/unit/test_config.py tests/unit/test_operator_database.py tests/unit/test_database_report_payload_lifecycle.py tests/contract/test_database_setup_lifecycle.py tests/contract/test_monthly_quota_lifecycle.py tests/contract/test_db_sync_lifecycle.py --basetemp .pytest_phase3_focus
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\mypy .
git diff --stat c49ab09 e8053ef
```

The source and test diff reports `3 files changed, 331 insertions(+), 274 deletions(-)`. The new SQL module accounts for 286 of the inserted lines. To review evidence without rerunning the app, read `before.log`, `after.log`, `legacy-reference.json`, `legacy-current.json`, `goldens.log`, `compare-receipts.log` and `verify-raw.log` in the private folder.

To undo the refactor, revert `e8053ef`. This restores the original SQL builders without a database migration. Phase 4 starts by measuring time and memory.
