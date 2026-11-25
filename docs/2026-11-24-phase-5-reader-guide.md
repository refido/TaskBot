# Phase 5 · How to read a TaskBot run

Start with the [three lookups in the README](../README.md#find-an-operators-input-result-and-quota). They show where the customer list comes from, where to read one result, and how to check a quota. This task also tested the proposed mypy configuration on the same source as the guide. The two adopted checks catch obsolete and overly broad type ignores. The full proposal produced five diagnostics. [Applied settings](../pyproject.toml#L26)

## How to check

The code baseline was `13efccb`. On this Windows installation the tools reported `ruff 0.17.6`, `mypy 2.4.1 (compiled: yes)` and `pytest 9.0.2`. The isolated `reference` and `current` snapshots contain the tracked source and lock file, with both operational dotenv files absent. In the commands below, `$p` is the local evidence folder. Its suite launcher prints the database name, verifies the PostgreSQL 18 cluster name, port and data directory, creates a disposable database, disables dotenv and runs `uv run --locked pytest`. Use fresh evidence labels for reruns.

```powershell
$p = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/phase5-20261124-d34a5e01'
$env:UV_PROJECT_ENVIRONMENT = 'D:/MyProject/TaskBot/.venv'
Set-Location (Join-Path $p 'reference')
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy .
uv run --locked powershell -NoProfile -File (Join-Path $p 'suite.ps1') reference before
uv run --locked powershell -NoProfile -File (Join-Path $p 'pairs.ps1')
uv run --locked python -I -B (Join-Path $p 'guide-permutations.py')
uv run --locked powershell -NoProfile -File (Join-Path $p 'guide-query.ps1')
# The original guide-lookups.ps1 parsed the README wording at beb593e.
# For the revised operator 2 example, see the November 25 follow-up linked below.
Set-Location (Join-Path $p 'current')
uv run --locked mypy --no-incremental --config-file (Join-Path $p 'proposal.toml') .
uv run --locked mypy --no-incremental --config-file (Join-Path $p 'narrow.toml') .
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy .
uv run --locked powershell -NoProfile -File (Join-Path $p 'suite.ps1') current after
uv run --locked powershell -NoProfile -File (Join-Path $p 'pairs.ps1')
uv run --locked powershell -NoProfile -File (Join-Path $p 'suite.ps1') current branches ("--junitxml="+(Join-Path $p 'branches.xml')) tests/unit/test_config.py tests/unit/test_customer_workflow.py tests/unit/test_page_objects.py tests/unit/test_transaction_outcome.py tests/unit/test_rate_limiter.py tests/unit/test_process_accounts.py tests/unit/test_operator_database.py tests/unit/test_account_runner.py tests/contract/test_transaction_processor.py tests/contract/test_reporting_and_main.py tests/contract/test_run_outcomes.py tests/integration/test_transaction_confirmation.py
uv run --locked mypy --no-incremental --config-file (Join-Path $p 'reference/pyproject.toml') (Join-Path $p 'ignore_probe.py')
uv run --locked mypy --no-incremental --config-file (Join-Path $p 'narrow.toml') (Join-Path $p 'ignore_probe.py')
```

## F114 · VERIFIED · The three operator lookups

- **Input.** For operator 2, `NIK_2` supplies the queue. The parser uses `tuple(nik.strip() for nik in raw_nik.split(",") if nik.strip())`. The numbered-account test verifies the order, duplicates, and precedence over the single-account input. [Numbered account](../src/infrastructure/config/settings.py#L119) · [Parser](../src/infrastructure/config/settings.py#L194) · [Input test](../tests/unit/test_config.py#L11)
- **One result.** Open `operators/<operator_id>/items.jsonl` under the run folder and read `status`. The reporter calls `self.file_writer.append_row(row)` before queuing the database write. The independent confirmation condition is `self.status == "completed" and bool(self.evidence.strip())`. Workflow milestones and retries have separate files. [File paths](../src/web/reporter.py#L958) · [Write order](../src/web/reporter.py#L1134) · [Confirmation](../src/application/models/transaction_outcome.py#L18)
- **Quota.** In the numbered operator table, read `KUOTA` and `MAX_KUOTA`. The mapping supplies `kuota_delta=1 if is_successful else 0`. Ordinary upserts check time and month. A distinct confirmed sale can count in the same month even at the same timestamp. [Mapping](../src/infrastructure/database/operator_store.py#L284) · [Quota and high-water rules](../src/infrastructure/database/_operator_sql.py#L93) · [Confirmed receipt case](../src/infrastructure/database/_operator_sql.py#L125)
- **Manual selection.** The first Lowokwaru SELECT in the owner's SQL notebook ran inside a read-only transaction against the disposable database `p1w_d34a5e01_0bb466f124` on `127.0.0.1:55432`. Output was `READ ONLY; selected rows 1 all quota <= 5`. The operator loop reads `for nik in self.config.nik`. The SQL notebook and the app’s input are separate steps. [Operator loop](../src/orchestration/transaction_processor.py#L95)

The readback followed the three names in the README against a dummy queue, an actual dummy-shop terminal row and its database record. It printed `PASS: guide input preserved 3 entries; terminal status completed; quota and high-water 3/3`.

<a id="current-guide-corrections"></a>

## F115 · VERIFIED · Outdated directions corrected

This finding **supersedes F16** for the current README and installed tooling. There are four precheck actions. `SKIP_REQUIRES_RECOVERY` means the skip has already been reported and the processor must restore the session. Known parsing failures write `skipped_nik_parsing_failed`; the contract test asserts that exact status and an empty retry list. A separate test covers an unexpected preparation exception. [Four actions](../src/application/models/customer_workflow.py#L10) · [Processor](../src/orchestration/transaction_processor.py#L179) · [Terminal assertions](../tests/contract/test_transaction_processor.py#L326) · [Unexpected preparation failure](../tests/unit/test_customer_workflow.py#L562)

The current terminal writer calls `_append_with_retry` for CSV and then JSONL. Terminal rows require disk sync, so a lasting failure on the second file can leave a CSV-only row. Event-file sync catches `OSError`. The optional session export and private quota journal have different locations from the daily business reports. The development instructions now use the Ruff and mypy installed by the lock file. [Row order](../src/infrastructure/reporting/file_writer.py#L60) · [Terminal sync](../src/infrastructure/reporting/file_writer.py#L160) · [Event sync](../src/web/reporter.py#L1438) · [Session export](../src/application/use_cases/export_session.py#L65) · [Journal](../src/infrastructure/database/quota_journal.py#L12)

## F116 · VERIFIED · Branch checks

<a id="branch-checks"></a>

The following groups cover each row of the README tables. The targeted test run printed `461 passed in 15.63s`; its JUnit report contained 461 cases and zero failures. The local shop supplied the external confirmation step. The screen-order example used fake screens and blocked network and disk writes.

| README cases | Observed result or source check |
| --- | --- |
| Direct sale, type only, consent only, type plus consent | The happy-path matrix checks `action is expected_action`. The eight-route dummy-shop case also checks receipts and terminal rows. [Happy-path matrix](../tests/unit/test_customer_workflow.py#L395) |
| NIB reminder alone or after type, consent, or both | The continued reminder is distinct from a customer update. Closing it records a skip. The guide’s W24 example printed `16 fake screen orders passed -> continue` and `16 fake screen orders passed -> restart_after_update`. [Continue](../tests/unit/test_customer_workflow.py#L621) · [Close](../tests/unit/test_customer_workflow.py#L673) |
| Immediate update or update after type, consent, or both | The service returns `RESTART_AFTER_UPDATE` after success. The processor test checks one final completion and no ordinary retry for restarting the same customer. [Update result](../src/application/services/transaction_prechecks.py#L341) · [Restart test](../tests/contract/test_transaction_processor.py#L1523) |
| Under 17, unregistered, daily registration limit, invalid registration, base restriction, unusual transaction | Separate handlers record a skip. The daily-limit case also checks database status 429 and zero quota delta. [Under 17, unregistered and daily limit](../src/application/services/transaction_prechecks.py#L722) · [Invalid, base and unusual cases](../src/application/services/transaction_prechecks.py#L915) · [DB check](../tests/unit/test_operator_database.py#L275) |
| Mismatch, cannot transact, fraud warning | A mismatch can proceed or end as a skip. The two close-only warnings persist their skips and request recovery. [Mismatch tests](../tests/unit/test_customer_workflow.py#L200) · [Close-only warnings](../tests/unit/test_customer_workflow.py#L268) |
| Monthly maximum, empty stock during a sale, empty stock at dashboard entry | The quota blocker skips the customer. The stock tests check one terminal result and stopping the affected operator. [Quota](../tests/unit/test_page_objects.py#L872) · [Dashboard stock](../tests/contract/test_transaction_processor.py#L450) · [Stock during sale](../tests/contract/test_transaction_processor.py#L904) |
| Confirmation challenge fails, with or without a retry signal | Failure produces a terminal failure result. An unclear sale outcome cannot create a completion or trigger another submission. [Failure outcome](../tests/contract/test_transaction_processor.py#L1643) · [Unconfirmed outcome](../tests/contract/test_transaction_processor.py#L855) |
| Invalid update input, missing form, missing confirmation, unowned confirmation, missing or unowned success, dashboard restore failure | Known input errors skip before filling the form. The service checks each required transition and the processor records an update error on failure. Tests assert that submission and confirmation timeouts do not repeat the action. [Input failure](../tests/unit/test_customer_workflow.py#L519) · [Required transitions](../src/application/services/transaction_prechecks.py#L244) · [One-shot tests](../tests/unit/test_customer_workflow.py#L935) · [Error result](../src/orchestration/transaction_processor.py#L277) |
| Another update after restart, registration limit during an update or action | A second update request ends in an error. The daily limit at an update boundary or in a click race produces a business skip. [Repeat update](../tests/contract/test_transaction_processor.py#L1601) · [Boundary tests](../tests/unit/test_customer_workflow.py#L804) |
| Expired session, transient general error, stale optional screen, disappearing blocker, autocomplete interception | Session and ordinary retries have separate bounds. The old screen gets checked again without repeating the completed action. A vanished blocker is re-resolved. The customer entry handles autocomplete with `press("Escape")`. [Retry tests](../tests/contract/test_transaction_processor.py#L1693) · [Stale screen](../tests/unit/test_customer_workflow.py#L881) · [Vanished blocker](../tests/unit/test_customer_workflow.py#L1010) · [Autocomplete](../src/infrastructure/browser/page_objects/dashboard_page.py#L872) |
| Concurrent update actions, eight skips within 48 seconds | Operators share update pacing. Skip pressure has its own settings and cooldown. [Pacing tests](../tests/unit/test_rate_limiter.py#L88) · [Configured window](../main.py#L41) · [Cooldown](../src/web/rate_limiter.py#L197) |
| Database commit failure, disabled sync, one account fails | The reporter keeps a pending row after a DB failure, a disabled DB preserves local reporting, and other account workers can finish. [Pending row](../tests/contract/test_reporting_and_main.py#L182) · [DB disabled](../tests/unit/test_account_runner.py#L410) · [Worker failure](../tests/unit/test_process_accounts.py#L170) |

## F117 · VERIFIED · Which pyproject settings earned their place

The project metadata, dependency lists, Python requirement, Ruff exceptions and existing psycopg2 import override already matched the proposal. `uv run --locked ruff check --show-settings main.py` listed 407 enabled rules. No package or lock change was needed. [Configuration](../pyproject.toml#L1)

- **Adopted two checks.** The current project passed `warn_unused_ignores` and `ignore-without-code`. In a two-line disposable example, the previous config printed `Success: no issues found in 1 source file`. The candidate reported `[ignore-without-code]` on a blanket suppression and `[unused-ignore]` on an obsolete one. Both checks enforce the repository's suppression policy. [Applied options](../pyproject.toml#L26)
- **Deferred the full proposal.** The exact proposed settings printed `Found 5 errors in 4 files (checked 144 source files)`, all `[redundant-expr]`. The locations were `customer_workflow.py:61,95`, `settings.py:31`, `process_account.py:22` and `matching.py:430`. The first four include runtime type guards on annotated inputs. For example, `not isinstance(limit, int)` protects callers supplying a value of the wrong runtime type. Removing a guard solely to satisfy static analysis would require a separate behavior decision. [Model validation](../src/application/models/customer_workflow.py#L61) · [Month validation](../src/application/models/customer_workflow.py#L95) · [Settings](../src/infrastructure/config/settings.py#L31) · [Account worker limit](../src/application/use_cases/process_account.py#L22) · [Fifth diagnostic](../src/vision/puzzle/matching.py#L430)
- **Future decisions.** The proposed strict override names zero modules. Naming only `src.application.dto.run_context` in the trial passed all 144 source files. Introduce a named strict module when its own modernization work starts. The proposed psycopg2 exemption would relax checks and the existing code passed without it. A stubs installation was **NOT RUN** because the proposal leaves that dependency commented out and requires separate approval. Discovery options and additional warnings can be evaluated with the module or test package they are intended to protect. Mypy documents that checking for unused override sections requires incremental mode to be disabled. [Official mypy configuration reference](https://mypy.readthedocs.io/en/stable/config_file.html#warn-unused-configs)

## F118 · VERIFIED · Local acceptance

The baseline was `13efccb`. The mypy settings are commit `29fbca8`. Both ran on Python 3.14.2 with uv 0.9.26, Ruff 0.17.6, mypy 2.4.1 and pytest 9.0.2. The ordered checks printed `154 files already formatted`, `All checks passed!` and `Success: no issues found in 144 source files` for both. The full suite printed `1450 passed in 71.80s` before the change and `1450 passed in 67.75s` after it. All 144 Python files and `uv.lock` matched the workspace and both snapshots. The configuration diff was `1 file changed, 2 insertions(+)`. No runtime module or type suppression was added.

The baseline and candidate golden runs each printed `PASS 7 pairs, 56 business file comparisons, both operator tables and diagnostic signatures`. Coverage included normal sales, update and restart, skips, and one-time and persistent file or database failures. All receipt columns matched. After restoring database access the result was `[2, 0, 1] -> [3, 1, 0] ; second drain identical`, in order of quota, receipts and pending entries. The suite and golden runner used separate disposable databases on `127.0.0.1:55432`.

## Open items

Live-site and production database verification were **NOT RUN**. The local results describe the dummy shop and test data.

The owner requested clearer points after reading the first version. On November 25 the owner accepted the revised guide. [F125 and the owner's answer](2026-11-25-operator-quick-guide.md#f125--verified--the-owner-accepted-the-revised-guide)
