# Recover quota after TaskBot or the machine stops

A confirmed sale now survives an interrupted TaskBot process when its recovery disk survives. TaskBot saves the work locally, sends the quota update to PostgreSQL, and removes the local entry only after PostgreSQL commits. An ID saved with the database update prevents a second increment if the acknowledgement was interrupted. The recovery command only works with the journal and the database. [Local delivery](../../src/infrastructure/database/quota_journal.py#L158) · [PostgreSQL receipt](../../src/infrastructure/database/operator_store.py#L733)

## What to do after an interruption

Revised on 2026-11-26 after the first real recovery. The earlier steps ran `drain` before the receipt check, which always fails while an item needs one. This guide describes the tool exactly as it behaves today. [Why it changed, F147–F151](2026-11-26-quota-recovery-tool-findings.md)

### The recovery at a glance (5W1H)

- **What.** A command that settles customers TaskBot was working on when it stopped. It records each one as a sale or as no sale, then sends the result to PostgreSQL.
- **Why.** TaskBot cannot tell on its own whether the shop finished that sale. Guessing could count quota twice or lose a sale. So it refuses to start that operator until a person decides.
- **Who.** The person who can open the shop's receipt history for that operator. Use the same Windows user and the same `.env` as the interrupted run, because the journal and the database target depend on both.
- **When.** When `uv run main.py` logs `account.run.fatal_error` with `Quota event <id> has no recorded outcome`, or after TaskBot, the browser or the machine stopped in the middle of a run. Run it while TaskBot is **not** running for that operator.
- **Where.** PowerShell in the project folder (`D:\MyProject\TaskBot`). The journal is under `%LOCALAPPDATA%\TaskBot\quota-recovery`, one folder per operator and database. The sale and quota go to the PostgreSQL database named in `.env`.
- **How.** For each operator in the error log: `list`, check the shop receipt, then `confirmed` or `no-sale`, then `list` again. Use `drain` only for items that already have an outcome. The steps are below.

### Commands

Replace `operator_01` with the operator ID from the error log (`operator_id=…`). Every command starts with `uv run python -m src.infrastructure.database.recover_quota <operator>`.

- **`list`** — show what is outstanding. Reads `.env` and the journal. It doesn't connect to PostgreSQL and doesn't change any entry.

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 list
  ```

- **`confirmed EVENT_ID RECEIPT_TIME`** — the shop's receipt proves a sale. Records it with the receipt's time and sends it to PostgreSQL.

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 confirmed EVENT_ID RECEIPT_TIME
  ```

- **`no-sale EVENT_ID`** — the shop proves there was no sale. Removes the open item; nothing is written for that customer.

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 no-sale EVENT_ID
  ```

- **`drain`** — send items that already have an outcome (**pending delivery** or **confirmed**) to PostgreSQL. It cannot settle a **needs receipt check** item.

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 drain
  ```

`EVENT_ID` is the first column of `list`. `RECEIPT_TIME` is the time printed on the shop's receipt, in the form `YYYY-MM-DDTHH:MM:SS+07:00`. Never copy a time from an example or from `list`.

### Step 1 · `list`: see what is outstanding

- **What.** One line per entry: event ID, status, the last four digits of the customer number (NIK), and a time. Nothing printed means nothing is outstanding for that operator.
- **Why.** The status says which command settles the entry.

  | Status in `list` | Meaning | The time shown is | Settle it with |
  | --- | --- | --- | --- |
  | **needs receipt check** | TaskBot started this customer and has no answer from the shop. | when TaskBot **started** the customer | Step 2, then `confirmed` or `no-sale` |
  | **confirmed** | The shop confirmed the sale before TaskBot stopped. | when the sale finished | `drain` |
  | **pending delivery** | The final result was saved but not yet sent to PostgreSQL. | when the sale finished | `drain` |

- **Who / When / Where.** Before any other recovery command, for each operator separately. Each operator has its own journal, so an event ID from operator 2 is unknown to operator 1.
- **How.** Run `list`. Write down the event ID, the four digits and the time. There is at most one **needs receipt check** item per operator.

### Step 2 · Check the shop's receipt history

- **What / Why.** Find out whether the shop actually sold to that customer. This is the only proof of the outcome; TaskBot's files and the database can't show it.
- **How.** In the shop, open that operator's receipt history. Look for the customer whose number ends in the four digits from `list`, at or shortly after the start time. Note the time on the receipt, with its time zone.
- **If you can't tell yet,** leave the item open and run nothing. TaskBot will keep refusing to start that operator, which is safer than a wrong answer.

### Step 3a · `confirmed`: the receipt shows a sale

- **What.** Marks the item as a completed sale at `RECEIPT_TIME`, then sends the sale and its quota to PostgreSQL in one database transaction.
- **Why.** So the customer's used quota matches what the shop sold.
- **Who / When.** Only after Step 2 found the receipt. Use the operator ID that `list` was run with.
- **Where.** The journal entry, then the operator's table in PostgreSQL. The command first runs the usual database setup, so its log also shows `Database setup started` and `Monthly quota reset started`.
- **How.**

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 confirmed EVENT_ID RECEIPT_TIME
  ```

  Success ends with `Quota recovery complete.`. Run `list` again; it should print nothing.
- **Take care.** There is no undo. The tool checks only that the time has a time zone, not that it is close to the start time. A wrong time stays in the database, and a sale that didn't happen uses one unit of quota. [F149](2026-11-26-quota-recovery-tool-findings.md#f149--verified--confirmed-accepts-any-receipt-time-that-has-a-time-zone)

### Step 3b · `no-sale`: the shop shows no sale

- **What.** Removes the open item. Nothing is written for that customer, so the quota stays as it was.
- **Why.** The customer can be served again in a later run.
- **Who / When.** Only after Step 2 proved there was no sale. Run either `confirmed` or `no-sale` for an event, never both.
- **How.**

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 no-sale EVENT_ID
  ```

  Success ends with `Quota recovery complete.`. Run `list` again; it should print nothing.

### Step 3c · `drain`: deliver outcomes that are already known

- **What.** Sends **confirmed** and **pending delivery** items to PostgreSQL, oldest first. Each local entry is removed only after PostgreSQL commits it. Sending the same item twice leaves the quota unchanged.
- **Why.** Usually TaskBot did save the outcome, but the database was unreachable or the process stopped before sending it.
- **When.** When `list` shows only **confirmed** or **pending delivery** items. An ordinary `uv run main.py` does the same delivery at startup, but then leaves that operator's new work unstarted for that run (`execution_status=not_started`).
- **How.**

  ```powershell
  uv run python -m src.infrastructure.database.recover_quota operator_01 drain
  ```

- **If a needs receipt check item remains,** `drain` delivers the other items and then stops with `RuntimeError: Quota event … has no recorded outcome`. That is expected and changes nothing for that item. Go back to Step 2. [F147](2026-11-26-quota-recovery-tool-findings.md#f147--verified--drain-always-fails-while-an-item-still-needs-a-receipt-check)

### Step 4 · Start TaskBot again

- **What / When.** Once `list` prints nothing for every operator in the error log, run `uv run main.py`.
- **Why.** On every launch TaskBot first checks each operator's journal. With nothing outstanding, that operator starts normally. If the check delivers an old result, that operator does no new work in that run. Review the customer list before the next sales run.

### Messages and what they mean

The tool shows errors as a Python traceback. Read the last line.

| Last line of the output | Meaning | What to do |
| --- | --- | --- |
| `Quota recovery complete.` | Everything for this operator is settled. | Step 4 |
| `RuntimeError: Quota event … has no recorded outcome. …` | An item still needs a receipt check. Nothing else is wrong. | Steps 2 and 3a or 3b |
| `ValueError: Unknown or already resolved quota event` | The event ID isn't open in **this operator's** journal: it belongs to another operator, it was mistyped, or it is already settled. Nothing was changed. | Run `list` for this operator. Use the operator ID from the error log that names this event. |
| `RuntimeError: Quota journal is locked or unavailable for this operator` | TaskBot (or another recovery) is using this operator's journal. | Wait until it finishes, then try again. |
| `… error: argument receipt_time: The receipt time must include its time zone` | `RECEIPT_TIME` has no `+07:00` (or other zone). This one is a short message, not a traceback. | Add the time zone from the receipt. |

Sources: [Recovery command](../../src/infrastructure/database/recover_quota.py#L23) · [Journal](../../src/infrastructure/database/quota_journal.py#L33) · [Startup handling](../../src/application/services/account_runner.py#L57)

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
