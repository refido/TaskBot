# Phase 2 · One rule for saved retry reports

**Accepted on November 23, 2026 for the local dummy shop and the separate PostgreSQL 18 test instance.** TaskBot now builds the retry section of the running summary and the final snapshot in one place. All 40 business-file comparisons matched byte for byte. Both operator tables and all dummy shop receipts matched in each of five paired runs. F84–F88 give the evidence. [Phase plan](../plans/2026-11-23-plan-modernization.md#4-phases-and-acceptance-gates)

## F84 · VERIFIED · What changed

Before this change, `TransactionReporter.write_files` and `_write_meta` each built the same ordered dictionary from `_compact_retry_report()`. Both assigned the stable operator ID to the saved `operator` and `operator_id` fields. The reporter normally starts with `self.operator = self.operator_id`. The new helper keeps the file rule explicit even if a caller later changes the old alias. Compare `git show c3ed06a:src/web/reporter.py` at lines 634–639 and 1312–1317 with the two calls to `retry_report = self._retry_report_for_file()`. [Initialization](../../src/web/reporter.py#L107) · [Final snapshot](../../src/web/reporter.py#L634) · [Shared helper](../../src/web/reporter.py#L796) · [Running summary](../../src/web/reporter.py#L1316)

The new test assigns a different dummy alias, records a retry, reads the summary immediately, then writes and reads the final snapshot. It checks that `get_retry_report()` still returns the alias, that both saved operator fields hold the ID, and that the snapshot contains the same retry section as the summary. The test passed against both versions. [Regression test](../../tests/contract/test_reporter_aggregation.py#L159)

## F85 · VERIFIED · Test results

The baseline was the clean `modernize` revision `c3ed06ac0f384f27cab17c68b7d2a472b824a145`. The original reporter’s Git blob was `58afae3007aac871fd48f5a677015db3ba6cee33`. The tested reporter and the workspace reporter both hashed to `6809f72cea08aafcd34f3ee82573a1142ebbe286`. Both copies of the updated test hashed to `e0e8475e98936580257ad01fd91461deeaa59030`. Python reported `Python 3.14.2`. The suite ran in a private copy of the checkout with dotenv disabled.

| Check | Exact pytest summary | Exit |
| --- | --- | --- |
| Full suite on the original revision | `1419 passed in 83.67s (0:01:23)` | 0 |
| New alias test on the original reporter | `1 passed in 0.17s` | 0 |
| Both reporting contract modules on the final candidate | `71 passed in 9.46s` | 0 |
| Full suite on the final candidate, including the new test | `1420 passed in 63.09s (0:01:03)` | 0 |

The existing tests also checked masked and unmasked histories, intermediate summary hashes, failed CSV and JSONL writes, and the order `csv → jsonl → enqueue → db_sync → summary → row_recorded`. The times above are test-run durations. Phase 2 made no performance claim. [Legacy file checks](../../tests/contract/test_reporter_aggregation.py#L131) · [Interrupted file writes](../../tests/contract/test_reporter_aggregation.py#L246) · [Write-order assertion](../../tests/contract/test_reporting_and_main.py#L103)

## F86 · VERIFIED · Five whole-app comparisons

Each row represents two runs, first with the original reporter and then with the candidate. Both used the same dummy shop URL, clock, run ID, report path and starting data for that pair. The fixture verified the test cluster name, data directory, major version and port (`127.0.0.1:55432`). It saved independent shop receipts, database snapshots and failure checkpoints. The test reader compared both operator tables’ column definitions, primary keys and every row. The final check printed `all 5 pairs rechecked from raw shop receipts, files and independent database snapshots; blocked web requests 0`.

| Dummy case | Shop receipts per run | CSV / JSONL rows | Quota gained by queued customers | Recorded run outcome |
| --- | ---: | ---: | ---: | --- |
| Eight ordinary sale routes | 8 | 8 / 8 | 8 | `completed` |
| Updates, same-customer restarts, a skip, then another sale | 5 | 6 / 6 | 5 | `completed_with_errors` |
| JSONL write fails after the CSV write | 1 | 1 / 0 | 0 | `completed` |
| First DB commit fails, retry succeeds | 1 | 1 / 1 | 1 | `completed` |
| DB commit fails both times | 1 | 1 / 1 | 0 | `failed` |

The complete filename lists matched. The eight business files in each pair were `run_meta.json`, `analytics.json`, `items.csv`, `items.jsonl`, `items_snapshot.json`, `retries.jsonl`, `summary.json` and `workflow_events.jsonl`. The comparator read their raw bytes, including empty files. A deliberate one-byte report change and a one-unit quota change in copies of the evidence each caused the comparator to reject the result.

## F87 · VERIFIED · Diagnostic evidence

The two application logs and the database event log met the Phase 1 rules for event names, levels, counts, run/operator/customer associations and expected failure or recovery order. Both screenshots from the partial-write case showed the dummy dashboard with “Fixture Operator”, “100 Tabung” and “Catat Penjualan”. Both matched the recorded failure event and had SHA-256 `39d8d68dd7503df83e1ed672ac6aa76ec824506ccbf4fcf86672379a61213aec`. The private checker printed `PASS: 5 paired comparisons; one changed report byte and one changed quota both rejected`. [Diagnostic acceptance rules](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure)

## F88 · VERIFIED · Known risk and rollback

**Follow-up repair.** A single interrupted write now recovers in the dummy shop. A lasting failure marks the run failed while the available database records the confirmed sale. The paragraph below records the original Phase 2 result. [Repair and test evidence](2026-11-23-terminal-file-recovery.md#f89--verified--what-the-operator-sees)

In the forced JSONL failure, the shop recorded **one sale**, the CSV and snapshot contained **one completed row**, the JSONL contained **zero rows**, and the customer’s quota stayed at **2**. Both versions marked persistence successful. Checking only the run status would miss that partial write. The evidence is the `jsonl` row in `verify-final.log`, the shop ledger and the before/after database snapshots. A change to that outcome belongs in a separately approved repair. This acceptance covers the synthetic runs above. Live daily sales were outside this check.

To roll back the code change, restore the two original dictionary expressions together and remove the helper. Rerun the tests and paired comparisons below. The production source diff touches only `src/web/reporter.py`.

## Commands and retained evidence

The complete pytest output, raw reports, test database snapshots and fixture scripts are in the private evidence directory below. The raw shop and database evidence stays on the machine. To recheck the saved comparisons from the project root, run the following PowerShell commands.

```powershell
$p = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/phase2-e45445ff'
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
& $py -I -B (Join-Path $p 'verify-final.py')
& $py -I -B (Join-Path $p 'audit-phase2.py')
```

The test and fixture commands used for acceptance are listed below. The suite wrapper printed the complete pytest invocation and saved stdout and stderr. The labels identify the frozen source version in use at execution. The matrix command ran with the private test-instance credential and wrote to `matrix.log`. Each pair used a fresh test database per revision.

```powershell
& $py -I -B (Join-Path $p 'suite.py') before
& $py -I -B (Join-Path $p 'suite.py') original-alias tests/contract/test_reporter_aggregation.py::test_saved_retry_reports_use_operator_id_when_legacy_alias_differs
& $py -I -B (Join-Path $p 'suite.py') candidate-focused tests/contract/test_reporter_aggregation.py tests/contract/test_reporting_and_main.py
& $py -I -B (Join-Path $p 'suite.py') candidate-full
& $py -B (Join-Path $p 'matrix.py') common updates jsonl db_once db_always
```

Read `before-suite.log`, `original-alias-suite.log`, `candidate-focused-suite.log` and `candidate-full-suite.log` for the full pytest output. Read `verified-final.json`, `audit-results.json` and the ten `pass-*` directories for each receipt, file and database comparison. The private `command-evidence.json` records the supporting commands and trimmed output.

```text
git diff --stat -- src/web/reporter.py tests/contract/test_reporter_aggregation.py
 src/web/reporter.py                         | 23 +++++++++++------------
 tests/contract/test_reporter_aggregation.py | 20 ++++++++++++++++++++
 2 files changed, 31 insertions(+), 12 deletions(-)
```
