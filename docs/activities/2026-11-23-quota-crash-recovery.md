# Recover quota after TaskBot or the machine stops

A confirmed sale now survives an interrupted TaskBot process when its recovery disk survives. TaskBot saves the work locally, sends the quota update to PostgreSQL, and removes the local entry only after PostgreSQL commits. An ID saved with the database update prevents a second increment if the acknowledgement was interrupted. The recovery command only works with the journal and the database. [Local delivery](../../src/infrastructure/database/quota_journal.py#L158) · [PostgreSQL receipt](../../src/infrastructure/database/operator_store.py#L733)

## What to do after an interruption

1. Use the same OS user, operator ID and database settings as the interrupted run. From the project folder, list outstanding items and deliver known outcomes. Use the appropriate operator ID in place of `operator_01`.

   ```powershell
   uv run python -m src.infrastructure.database.recover_quota operator_01 list
   uv run python -m src.infrastructure.database.recover_quota operator_01 drain
   ```

2. An item marked **needs receipt check** means processing started and TaskBot has no saved answer from the shop. Check the shop’s own receipt history using the time and masked customer number from the list. If the receipt confirms a sale, enter its actual time with its time zone. Replace `EVENT_ID` and the example time. If the shop proves there was no sale, use the second command. Leave the item pending while the answer is unknown.

   ```powershell
   uv run python -m src.infrastructure.database.recover_quota operator_01 confirmed EVENT_ID 2026-11-23T12:00:00+07:00
   uv run python -m src.infrastructure.database.recover_quota operator_01 no-sale EVENT_ID
   ```

3. An empty list means that operator and destination have no outstanding entries. On an ordinary app launch, TaskBot first checks the journal. If it recovers prior quota, it leaves that operator’s new work unstarted and records `execution_status=not_started`. Review the input list before starting a fresh sales run. Other operators have independent journals. An unresolved item or an already-running writer prevents a second writer from taking over. [Recovery command](../../src/infrastructure/database/recover_quota.py#L21) · [Startup handling](../../src/application/services/account_runner.py#L56)

## F92 · VERIFIED · Where the record lives

- Before work on a customer, TaskBot commits an open item to a private SQLite file. When the shop confirms the sale, it saves that confirmation before returning to the dashboard or writing final reports. The terminal row then supplies the same finished time used in the business report. A hard stop before that row uses the earlier saved confirmation. A zero-quota skip keeps its usual report and database path. [Start and confirmation](../../src/infrastructure/database/quota_journal.py#L73) · [Confirmation call](../../src/orchestration/transaction_processor.py#L434) · [Terminal row](../../src/infrastructure/database/report_syncer.py#L51)
- On Windows the journal lives under `%LOCALAPPDATA%\TaskBot\quota-recovery`; on POSIX it uses the user’s state directory. Each destination has a separate folder keyed by PostgreSQL host, port, database, operator table and operator ID. `pending.sqlite3` holds outstanding work, including the customer number needed for the database. `owner.sqlite3` provides the exclusive writer lock. Keep this folder private and retain it when replacing or reinstalling the app. [Path and lock](../../src/infrastructure/database/quota_journal.py#L10) · [Destination binding](../../src/infrastructure/database/report_syncer.py#L24)
- The database role needs permission to create and use `public.taskbot_quota_receipts`. Each entry contains the event UUID, operator table, customer number, event time and status. TaskBot commits it in the **same transaction** as the quota update. Replay of the same ID leaves quota alone. Two distinct confirmed sales can share a timestamp and each counts once. A recovered prior-month sale stays recorded and does not consume current-month quota. [Schema and durability checks](../../src/infrastructure/database/operator_store.py#L558) · [Commit setting](../../src/infrastructure/database/operator_store.py#L629) · [Database tests](../../tests/contract/test_quota_receipts_postgres.py#L56)

## F93 · VERIFIED · Crash tests

Each test began with quota 2 in the isolated PostgreSQL 18 instance. We terminated the dummy-shop app with `os._exit(77)`, started a fresh Python process and ran recovery twice. Shop receipts came from the separate dummy shop. Quotas and database receipts came from a separate PostgreSQL connection.

| Where the process stopped | Shop receipts | Quota at stop → after recovery | What settled the event |
| --- | ---: | --- | --- |
| Item started, before a sale | 0 | 2 → 2 | Owner path verified no sale |
| Shop had a receipt, local confirmation not yet saved | 1 | 2 → 3 | Owner path confirmed the receipt and its time |
| Confirmation saved, before terminal report | 1 | 2 → 3 | Automatic delivery |
| Terminal row saved locally, before reporting completed | 1 | 2 → 3 | Normal startup recovered quota and left the shop unopened for this operator |
| Inside PostgreSQL, before commit | 1 | 2 → 3 | Uncommitted receipt and quota rolled back together, then recovered |
| PostgreSQL committed, before local acknowledgement | 1 | 3 → 3 | Existing database receipt recognized |

All six finished with zero pending entries. Each confirmed case ended with one database receipt. The no-sale case ended with zero. The tests exercise abrupt process loss on the local machine. A physical power cut was not performed. Recovery assumes the journal storage survives and honors flushes, or the database commit survives. Losing both copies requires an independent shop record or backup. Database-disabled runs and crashes predating this feature have no new journal to replay.

## F94 · VERIFIED · Tests and rollback

The baseline was `6371ed3`. The before suite printed `1431 passed in 51.01s`. The final full suite printed `1445 passed in 78.94s (0:01:18)`, including the real PostgreSQL tests. The two new contract modules separately printed `14 passed in 1.90s`. They cover rollback, replay, distinct late and equal-time receipts, month rollover, rejection of unlogged tables and re-import of an already delivered business report. [Crash tests](../../tests/contract/test_quota_crash_recovery.py) · [PostgreSQL tests](../../tests/contract/test_quota_receipts_postgres.py)

Seven paired whole-app runs matched on all **56 business-file comparisons**, both operator tables, shop receipts and diagnostic event checks. The pairs covered a clean sale, one-time and persistent JSONL failures, one-time and persistent DB failures, customer updates and ordinary routes. After recording the persistent DB failure, we restored database access for that dummy case and ran the recovery command twice. The independent readback showed `[quota, database receipts, pending entries]` moving from `[2, 0, 1]` to `[3, 1, 0]`. The second recovery returned the same result.

Exact commands used in the isolated checkouts are shown below. The test launcher printed the pytest command and saved complete output. It provided a new disposable database for the opt-in tests. The whole-app launchers used the local dummy shop and the guarded test instance on port 55432.

```powershell
$ev = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification'
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
& $py -I -B (Join-Path $ev 'quota-0893a30d/suite.py') before
& $py -I -B (Join-Path $ev 'quota-0893a30d/accepted.py')
& $py -I -B (Join-Path $ev 'acceptedcrash-45a12f05/crashes.py')
& $py -I -B (Join-Path $ev 'acceptedgold-37984ff0/goldens.py')
& $py -I -B (Join-Path $ev 'acceptedgold-37984ff0/verify-raw.py')
```

To review the retained evidence, read `before-suite.log`, `accepted-contracts.log` and `accepted-suite.log` beside the suite launcher. The crash directory contains `crashes.json`, the process logs and the shop-test fixtures. The golden directory contains `goldens.json`, the raw before/after evidence, `verify-raw.log` and `db-recovery.json`. The last command consumes the deliberately pending event in a fresh test pair.

Before rolling back, settle pending events and verify each operator’s list is empty. Keep the receipt table with the operator tables in the same PostgreSQL backup. Restoring an older database while discarding the matching receipts would break the evidence needed to distinguish a replay from a new sale.
