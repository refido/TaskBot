# A confirmed sale when a report write fails

This repair addresses F88 from Phase 2. It changes the outcome of an interrupted local write. A customer whose sale was confirmed can have **a completed sale and a failed report**. The quota counts the sale once when the database is available. [Original evidence](2026-11-23-phase-2-reporting.md#f88--verified--known-risk-and-rollback)

## F89 · VERIFIED · What the operator sees

These are whole-app results from the dummy shop and the separate local PostgreSQL 18 cluster. The same dummy customer started each run at quota 2. The shop ledger contained one receipt and one submit in every row below. Counts come from the files on disk and an independent database connection.

| What happened | CSV / JSONL rows | Final quota | Run / persistence status |
| --- | --- | ---: | --- |
| Clean sale, before and after | 1 / 1 | 3 | `completed` / `successful` |
| One interrupted JSONL write, before | 1 / 0 | 2 | `completed` / `successful` |
| One interrupted JSONL write, after | 1 / 1 | 3 | `completed` / `successful` |
| JSONL stays unwritable, before | 1 / 0 | 2 | `completed` / `successful` |
| JSONL stays unwritable, after | 1 / 0 | 3 | `failed` / `failed` |

**If a live run reports this failure**, look in `run_meta.json` under `account_outcomes` for the operator. In the permanent-failure test, `transaction_status` was `completed` and `persistence_status` was `failed`. The confirmed row remained in `items_snapshot.json`. Reconcile the receipt, the snapshot and the quota before taking further action. Submitting the customer again would be a new sale. If the disk also prevents the final snapshot from being written, use the shop receipt and the database record to investigate. [Finalization order](../src/application/services/account_runner.py#L86)

## F90 · VERIFIED · How the fix works

- **A file retry stays inside the report writer.** The writer saves the file offset before each append. An empty tail permits one more attempt at that file. If the file contains bytes from the row, the writer compares them with the exact encoded row and appends only a verified missing suffix. A full matching row is synced without appending a duplicate. Unexpected bytes, a replaced file or an unresolved sync error stop further appends to that stream for this writer. The regression checks cover CSV, JSONL, a split UTF-8 character, a completed write followed by an error, and a failed disk sync. [Writer](../src/infrastructure/reporting/file_writer.py#L65) · [Regression tests](../tests/contract/test_terminal_file_recovery.py#L22)
- **The database can still record the sale.** After a terminal file error, the reporter retains the row for the configured database callback. It moves that row into the existing queue ahead of a later customer, or at the start of finalization. Repeated finalization cannot enqueue it twice. The reporter attempts the snapshot and summary, then raises a persistence error for unresolved writes. The account runner still flushes and closes the database. [Failure handling](../src/web/reporter.py#L1106) · [Queue order](../src/web/reporter.py#L1159) · [Final status](../src/web/reporter.py#L678) · [Repeated finalization test](../tests/contract/test_terminal_file_recovery.py#L74)

**Scope.** The fallback queue is held in memory. A process or machine that stops before the next row or finalization can lose that pending work. An unavailable database can also prevent a quota update. Recovery from a hard stop and repair of historical live records were outside this change. [Pending rows](../src/web/reporter.py#L135) · [Database flush and error handling](../src/application/services/account_runner.py#L98)

## F91 · VERIFIED · Tests and comparison

| Check | Result |
| --- | --- |
| Full suite on the original revision `cd11c97` | `1420 passed in 51.91s` |
| New regression cases on the original revision | `11 failed in 0.53s` |
| Reporting and account tests on the repaired version | `151 passed in 7.68s` |
| Full suite on the repaired version | `1431 passed in 66.36s (0:01:06)` |

The paired scenarios were a clean sale, one JSONL interruption, a lasting JSONL failure, eight ordinary routes, updates with a skip, a DB commit that fails once and a DB commit that fails twice. Each pair used the same local URL, test clock, output path and seeded database state. The app was run only against the dummy shop and the isolated test cluster on port 55432.

The final matrix printed `PASS 7 pairs, 14 isolated runs; no blocked web requests`. An independent readback compared all 40 business files across the five control pairs, both operator tables, receipts and diagnostic events. All matched. For the recovered interruption, all eight business files and both tables matched the clean sale. In the lasting-failure pair, the corrected database matched the clean sale and only `run_meta.json` changed among the eight business files. The process exit changed from 0 to 1. The dashboard screenshot matched the previously reviewed image, and the logs linked it to the confirmed sale and file error. See `matrix.log` and `verify-repair.log`.

The private evidence directory contains the original and final database snapshots for both operator tables, the shop ledgers, business files, diagnostic logs and fault checkpoints. The original full-suite log is in `repair-e7cdd417/before-suite.log`. The final run logs and the read-only comparison script are in `repairfinal-0fa566a5`. Both are under `%LOCALAPPDATA%/TaskBot/phase1-pg18/verification`.

The following commands identify the checks. The suite wrapper sets an isolated working directory and saves complete pytest output in `<label>-suite.log`. The matrix command used a fresh database for each run and the private test credential. To recheck the stored reports and database snapshots, run only the final command.

```powershell
$ev = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification'
$before = Join-Path $ev 'repair-e7cdd417'
$p = Join-Path $ev 'repairfinal-0fa566a5'
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
& $py -I -B (Join-Path $before 'suite.py') before
& $py -I -B (Join-Path $p 'suite.py') original-regression tests/contract/test_terminal_file_recovery.py
& $py -I -B (Join-Path $p 'suite.py') focused tests/contract/test_terminal_file_recovery.py tests/contract/test_reporting_and_main.py tests/contract/test_reporter_aggregation.py tests/unit/test_account_runner.py
& $py -I -B (Join-Path $p 'suite.py') after
& $py -I -B (Join-Path $p 'repair-matrix.py')
& $py -I -B (Join-Path $p 'verify-repair.py')
```
