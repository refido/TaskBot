# Quota recovery tool · findings from the first real recovery and a revised guide

- **What happened.** On 2026-11-26, `uv run main.py` stopped both operators with `Quota event … has no recorded outcome`. Each operator had one open journal entry from an earlier run that stopped partway through a customer. While following the recovery guide, the owner ran into the problems below. Each one is reproduced here with a throwaway journal and dummy data.
- **What is true now.** The recovery tool works as written, but it is hard to use correctly. The old guide told the operator to run `drain` before resolving the open item, which always fails (F147). A wrong operator and an already resolved event give the same message (F148). `confirmed` accepts any receipt time, even one before TaskBot started the customer (F149). `list` shows too little to find the customer in the shop (F150). One `confirmed` on 2026-11-26 used an example time instead of the shop's receipt time (F151).
- **What changed.** Documentation only. The guide in [Recover quota after TaskBot or the machine stops](2026-11-23-quota-crash-recovery.md#what-to-do-after-an-interruption) now follows the 5W1H format (what, why, who, when, where, how), with separate sections for `list`, `drain`, `confirmed` and `no-sale` and a bullet list of commands. It still describes the tool exactly as it behaves today. The tool fixes are a proposed phase in the [modernization plan](../plans/2026-11-23-plan-modernization.md#4-phases-and-acceptance-gates), waiting on the owner's Q8–Q10.

## How to check

From the project root in PowerShell. The reproduction imports only the journal and the receipt-time parser, from a separate worktree with no `.env`, and writes to an empty scratch folder. No database, shop or network is used.

```powershell
$work = Join-Path $env:TEMP 'taskbot-recovery-check'
git worktree add --detach "$work\tree" HEAD
New-Item -ItemType Directory "$work\journal" | Out-Null
$env:PYTHON_DOTENV_DISABLED = '1'
& .\.venv\Scripts\python.exe -I -B "$work\reproduce_recovery_tool.py" "$work\tree" "$work\journal"
Push-Location "$work\tree"
& D:\MyProject\TaskBot\.venv\Scripts\python.exe -I -B -c "import sys; sys.path.insert(0, '.'); from src.infrastructure.database.recover_quota import main; main(['operator_01','confirmed','x','2026-11-25T12:23:40'])"
"exit=$LASTEXITCODE"
Pop-Location
git worktree remove "$work\tree"
npm exec --offline -- markdownlint-cli2 docs/activities/2026-11-26-quota-recovery-tool-findings.md docs/activities/2026-11-23-quota-crash-recovery.md docs/plans/2026-11-23-plan-modernization.md
```

Save the script below as `$work\reproduce_recovery_tool.py` first. It is a throwaway check, so it is not part of the repository. It uses a dummy customer number of zeros.

<details>
<summary>reproduce_recovery_tool.py</summary>

```python
"""Reproduce the quota recovery tool behaviors with a throwaway journal and dummy data."""

import argparse
import sys
from pathlib import Path

worktree = Path(sys.argv[1])
journal_root = Path(sys.argv[2])
sys.path.insert(0, str(worktree))

from src.infrastructure.database.quota_journal import QuotaJournal  # noqa: E402
from src.infrastructure.database.recover_quota import receipt_time  # noqa: E402

DESTINATION = ("localhost", 5432, "dummy_db", "dummy_table")
DUMMY_CUSTOMER_NUMBER = "0000000000000000"
STARTED_AT = "2026-11-25T12:20:24+07:00"


def show(label, action):
    try:
        result = action()
        print(f"{label}: OK -> {result!r}")
    except Exception as exc:  # noqa: BLE001 - print every outcome for the evidence
        print(f"{label}: {type(exc).__name__}: {exc}")


operator_one = QuotaJournal(journal_root, (*DESTINATION, "operator_01"), "operator_01")
operator_two = QuotaJournal(journal_root, (*DESTINATION, "operator_02"), "operator_02")
operator_one.begin(DUMMY_CUSTOMER_NUMBER, STARTED_AT, "dummy-source")
operator_two.begin(DUMMY_CUSTOMER_NUMBER, STARTED_AT, "dummy-source")
event_one = operator_one.active_id
event_two = operator_two.active_id

print("1. drain with an open item, then the same check recover_quota runs")
show("   drain delivered", lambda: operator_one.drain(lambda *args: None))
show("   require_resolved", operator_one.require_resolved)

print("2. open item payload keys (all the list command can show)")
show("   keys", lambda: sorted(operator_one.open_item(event_one)))

print("3. event of operator_02 reconciled in the operator_01 journal")
show("   reconcile", lambda: operator_one.reconcile(event_two, confirmed_at=None))

print("4. receipt time 1 day BEFORE the start, accepted by the CLI parser")
early = receipt_time("2026-11-24T12:00:00+07:00")
show("   receipt_time", lambda: early)
show("   reconcile confirmed", lambda: operator_one.reconcile(event_one, confirmed_at=early))

print("5. no-sale on the event that was just confirmed")
show("   reconcile no-sale", lambda: operator_one.reconcile(event_one, confirmed_at=None))

print("6. receipt time without a time zone")
show("   receipt_time", lambda: receipt_time("2026-11-25T12:23:40"))
try:
    receipt_time("2026-11-25T12:23:40")
except argparse.ArgumentTypeError:
    pass

operator_one.close()
operator_two.close()
```

</details>

Expected output, recorded at revision `bf89f7d` with Python 3.14.2 (the event ID is random on each run):

```text
1. drain with an open item, then the same check recover_quota runs
   drain delivered: OK -> 0
   require_resolved: RuntimeError: Quota event c43db370-f0d8-457f-b05d-0c5ead6c986a has no recorded outcome. Check the shop receipt and use the quota recovery command.
2. open item payload keys (all the list command can show)
   keys: OK -> ['nik', 'operator_id', 'started_at']
3. event of operator_02 reconciled in the operator_01 journal
   reconcile: ValueError: Unknown or already resolved quota event
4. receipt time 1 day BEFORE the start, accepted by the CLI parser
   receipt_time: OK -> '2026-11-24T12:00:00+07:00'
   reconcile confirmed: OK -> None
5. no-sale on the event that was just confirmed
   reconcile no-sale: ValueError: Unknown or already resolved quota event
6. receipt time without a time zone
   receipt_time: ArgumentTypeError: The receipt time must include its time zone
```

The command-line parser with a time that has no zone stops before reading `.env`:

```text
usage: -c operator confirmed [-h] event_id receipt_time
-c operator confirmed: error: argument receipt_time: The receipt time must include its time zone
exit=2
```

The markdownlint result is recorded under [Open items](#open-items). The gate and the golden master were **NOT RUN**, because only Markdown changed.

## F147 · VERIFIED · `drain` always fails while an item still needs a receipt check

- **Claim.** `drain` sends only entries with a known outcome to PostgreSQL. It then checks that no entry is still open and raises if one is. So while a **needs receipt check** item exists, `drain` delivers nothing for it and always ends in a traceback. The old guide listed `drain` in step 1, before the receipt check in step 2.
- **Evidence.** [quota_journal.py:187-189](../../src/infrastructure/database/quota_journal.py#L187-L189) selects only `ready IN (1, 2)`:

  ```python
  while row := self._db.execute(
      "SELECT id, source, payload FROM events WHERE ready IN (1, 2) ORDER BY sequence LIMIT 1"
  ).fetchone():
  ```

  [recover_quota.py:62-64](../../src/infrastructure/database/recover_quota.py#L62-L64) runs the open-item check after delivery:

  ```python
  syncer.finish_delivery()
  journal.require_resolved()
  print("Quota recovery complete.")
  ```

  [recover_quota.py:41-66](../../src/infrastructure/database/recover_quota.py#L41-L66) has `try`/`finally` and no `except`, so the error reaches the operator as a Python traceback. Reproduction step 1: `drain delivered: OK -> 0`, then `RuntimeError: Quota event … has no recorded outcome`.
- **Behavior.** Unchanged; this finding only records it. The revised guide puts `drain` after the receipt check and says when it fails.
- **Revision and tools.** `bf89f7d`, Python 3.14.2.

## F148 · VERIFIED · A wrong operator and an already resolved event give the same message

- **Claim.** Each operator has its own journal folder. An event ID used with the wrong operator, a mistyped ID and an event that was already resolved all raise `ValueError: Unknown or already resolved quota event` as a traceback. The message does not say which case happened, or which operator owns the event.
- **Evidence.** The journal folder is keyed by host, port, database, table and operator ID: [report_syncer.py:41-50](../../src/infrastructure/database/report_syncer.py#L41-L50). The lookup only finds open items in that folder: [quota_journal.py:148-154](../../src/infrastructure/database/quota_journal.py#L148-L154):

  ```python
  row = self._db.execute(
      "SELECT payload FROM events WHERE ready=0 AND id=?", (event_id,)
  ).fetchone()
  if row is None:
      raise ValueError("Unknown or already resolved quota event")
  ```

  Reproduction step 3 (operator 2's event in operator 1's journal) and step 5 (`no-sale` after `confirmed`) print the same `ValueError`.
- **Behavior.** Unchanged. Neither failure writes anything: `open_item` raises before the `DELETE` or `UPDATE` in [quota_journal.py:166-178](../../src/infrastructure/database/quota_journal.py#L166-L178), inside the same SQLite transaction.
- **Revision and tools.** `bf89f7d`, Python 3.14.2.

## F149 · VERIFIED · `confirmed` accepts any receipt time that has a time zone

- **Claim.** The receipt-time parser checks only the ISO format and that a time zone is present. Nothing compares the time with when TaskBot started the customer, or with the current time. A time a day **before** the start is accepted and becomes the sale's `finished_at`.
- **Evidence.** [recover_quota.py:11-20](../../src/infrastructure/database/recover_quota.py#L11-L20):

  ```python
  timestamp = datetime.fromisoformat(value)
  ...
  if timestamp.utcoffset() is None:
      raise argparse.ArgumentTypeError("The receipt time must include its time zone")
  return timestamp.isoformat()
  ```

  [quota_journal.py:174](../../src/infrastructure/database/quota_journal.py#L174) stores it: `payload.update(finished_at=confirmed_at, status="completed")`. Reproduction step 4: a time one day before `started_at` gives `reconcile confirmed: OK`. Step 6: only a missing time zone is refused.
- **Behavior.** Unchanged. A check would change exit codes and stderr, so it needs owner approval (Q9 in the plan).
- **Revision and tools.** `bf89f7d`, Python 3.14.2.

## F150 · VERIFIED · `list` shows too little to find the customer in the shop

- **Claim.** For each entry, `list` prints the event ID, the status label, the last four digits of the customer number (NIK, the national ID number the shop uses) and one time. An open item stores only the customer number, the operator ID and the start time, so a name or customer type is not available from the journal. The path of the interrupted run's report is stored as `source` but not printed.
- **Evidence.** What `list` prints: [recover_quota.py:45-57](../../src/infrastructure/database/recover_quota.py#L45-L57):

  ```python
  masked = "****" + (nik[-4:] if len(nik) > 4 else "")
  print(
      row["id"],
      labels[row["ready"]],
      masked,
      payload.get("finished_at") or payload.get("started_at"),
  )
  ```

  What an open item holds: [quota_journal.py:79-88](../../src/infrastructure/database/quota_journal.py#L79-L88), `"nik"`, `"operator_id"`, `"started_at"`, plus the `source` column. Reproduction step 2: `['nik', 'operator_id', 'started_at']`. The operator table has the customer's name and type ([operator_store.py:266-276](../../src/infrastructure/database/operator_store.py#L266-L276), `nama_konsumer`, `jenis_pengguna`), and the source report has that run's workflow events.
- **Behavior.** Unchanged. Showing more detail changes stdout and exposes more customer data on screen, so it is plan question Q8.
- **Revision and tools.** `bf89f7d`, Python 3.14.2.

## F151 · UNVERIFIED · One recovered sale may have the wrong time, or may not be a sale

- **Claim.** On 2026-11-26 the owner resolved operator 1's open event `4c6ed10e…` with `confirmed` and the time `2026-11-25T12:23:40+07:00`. That time was an example in the agent's chat reply, not a time read from the shop's receipt. The command succeeded, so PostgreSQL now has a completed sale with that time and one more unit of quota used for that customer.
- **Evidence.** The owner's pasted output ended with `Report row upserted into database` and `Quota recovery complete.`, and a later `list` for operator 1 printed nothing. The agent did not run these commands and did not read the database, so this is **owner-reported**. The code path is F149.
- **How to verify.** Look up operator 1's receipt history in the shop for that customer around 2026-11-25 12:22:56 +07:00 (the start time `list` showed). A sale at another time leaves only the time wrong. No sale means the quota for that customer is one too high. The tool has no undo for `confirmed`, so a correction is a manual database change. It needs its own approved task (plan Q10).
- **Revision and tools.** `bf89f7d`.

## Open items

- **Owner questions.** Plan [Q8 · How much customer detail should `list` show?](../plans/2026-11-23-plan-modernization.md#questions-and-answers), Q9 (receipt-time checks) and Q10 (correcting `4c6ed10e…` if it was not a sale).
- **Operator 2.** Event `b13ecd89…` was still open in the owner's last `list`. It needs the receipt check, then `operator_02 confirmed …` or `operator_02 no-sale …` with that operator's ID.
- **Branch difference.** The journal and its startup check exist only on `modernize`, added in `290780f`. `main` has neither, so an interrupted run does not block the next one there. F92–F94 record this as a deliberate safety feature.
- **Markdownlint.** markdownlint-cli2 0.24.2, after the final edit:

  ```text
  npm exec --offline -- markdownlint-cli2 docs/activities/2026-11-26-quota-recovery-tool-findings.md docs/activities/2026-11-23-quota-crash-recovery.md docs/plans/2026-11-23-plan-modernization.md
  Linting: 3 files
  Summary: 0 issues in 0 files
  npm run --silent lint:md
  Linting: 21 files
  Summary: 0 issues in 0 files
  ```
