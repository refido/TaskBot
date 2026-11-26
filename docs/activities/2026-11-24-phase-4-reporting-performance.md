# Phase 4 · Faster report redaction

**Complete on November 24, 2026 for the local dummy shop and PostgreSQL 18 test instance.** At 1,036 rows, the report took 31.2% less time with NIK masking on and 41.5% less with it off. All 56 business-file comparisons and both operators' database records matched in the full repeat. The whole-shop timing ranges overlapped. The implementation is `9f1933d`. F108–F113 give the measurements, the first failed comparison and the repeat result.

## F108 · VERIFIED · Where the time went

TaskBot checks text before saving it to a public report. On the 1,036-row dummy workload, Python's profiler attributed 5.220 of 6.097 seconds to the recursive public-value check, including its children. It attributed 1.950 seconds to 726,025 calls to `sanitize_text`. Building public rows accounted for 0.115 seconds and the two calls to `write_files` for 0.257 seconds. These times overlap. The expensive part was checking the growing report as each row arrived. [Metadata write](../../src/web/reporter.py#L1347) · [JSON writer](../../src/infrastructure/reporting/file_writer.py#L129)

The change is in one function. An email search needs an `@`, a labeled secret needs `:` or `=`, and a 16-digit NIK needs at least 16 characters. The function checks those conditions before running the corresponding regular expression. It still checks registered private values for **every** string, including a plain word with no punctuation. It also keeps the original handling of Python string subclasses. The original expressions and their order are visible in the diff against `f03f9aa`. [Expressions](../../src/privacy.py#L8) · [Changed function](../../src/privacy.py#L54) · [Regression tests](../../tests/unit/test_privacy.py#L7)

## F109 · VERIFIED · Time and memory for the report alone

Two dummy operators produced 14 files per run, totaling 299,876 bytes at 224 rows and 1,323,002 bytes at 1,036 rows. The last row was a quota skip. Each version had one warm-up and five timed runs per size and masking setting. Masked runs also registered a dummy private value. The timer included building and reading back the reports and preparing DB records in memory. The working-set sampler took a reading every 10 ms and at the run boundaries. The last column shows the median of those sampled peaks, in MiB.

| Rows | NIK masking | Median before → after | Time saved | Peak memory before → after |
| ---: | --- | ---: | ---: | ---: |
| 224 | Off | 211.97 → 143.70 ms | 32.2% | 46.30 → 46.39 |
| 1,036 | Off | 5,227.44 → 3,058.66 ms | 41.5% | 49.86 → 49.77 |
| 224 | On | 263.10 → 197.57 ms | 24.9% | 46.35 → 46.35 |
| 1,036 | On | 6,681.79 → 4,597.25 ms | 31.2% | 50.10 → 50.32 |

**Why use paired measurements?** The first independent processes gave 2,379.87 → 3,002.82 ms at 1,036 rows, and the candidate alone ranged from 1,579.18 to 3,181.30 ms. That comparison was inconclusive. For the table, both versions used the same Python process, imported modules and fixture. The runner alternated which function body went first in successive pairs. All five candidate times beat all five original times at 1,036 rows, with masking both on and off. At 224 masked rows, the ranges overlapped and one pair was slower. The largest increase in median report memory was 0.22 MiB. The per-run memory ranges overlapped in all four comparisons.

| Rows / mask | Five before times, ms | Five after times, ms |
| --- | --- | --- |
| 224 / off | 214.81, 219.26, 211.12, 211.80, 211.97 | 145.86, 142.69, 143.70, 144.70, 143.26 |
| 1,036 / off | 5,227.44, 5,167.69, 5,114.28, 5,535.76, 5,523.14 | 3,118.64, 2,954.77, 2,914.58, 3,058.66, 3,071.83 |
| 224 / on | 262.36, 263.10, 266.62, 261.07, 357.17 | 185.00, 184.87, 218.36, 197.57, 431.26 |
| 1,036 / on | 6,567.56, 6,898.89, 6,681.79, 6,573.86, 6,814.36 | 4,623.30, 4,567.96, 4,654.85, 4,497.68, 4,597.25 |

Every warm-up and measured run matched its file manifest, which includes the path, length and SHA-256 of each file. At 1,036 rows the digest was `698472576fe6fa9bda34acfe5552c8d92aca39c63ecf7a56f618958bc502835a` with masking off and `4f45f02bc7815cf493ee0efd082ca32a1c40e9a462cdcb33acaf5480612f9372` with masking on.

| Rows / mask | Five before peak working sets, MiB | Five after peak working sets, MiB |
| --- | --- | --- |
| 224 / off | 46.21, 46.28, 46.30, 46.48, 46.50 | 46.23, 46.24, 46.39, 46.39, 46.51 |
| 1,036 / off | 49.95, 49.72, 49.77, 49.86, 49.86 | 49.94, 49.72, 49.72, 49.77, 49.84 |
| 224 / on | 46.27, 46.35, 46.35, 46.43, 46.43 | 46.34, 46.34, 46.35, 46.35, 46.50 |
| 1,036 / on | 50.08, 50.10, 50.34, 49.82, 50.15 | 50.17, 50.45, 50.32, 50.40, 50.28 |

The archived B36 fixture initially failed with `io.UnsupportedOperation: fileno` because a memory-only file has no OS file descriptor. Both versions used the same fixture adapter. Each in-memory file supplies a sentinel descriptor and the replacement for `os.fsync` accepts only that descriptor. The audit hook rejects physical writes and database connections. The whole-app checks use real files and the normal durability code. [Original benchmark, including the input generator](2026-11-23-phase-1-behavior-baseline.md#b36) · [Durable row writer](../../src/infrastructure/reporting/file_writer.py#L160)

## F110 · VERIFIED · Whole dummy-shop time and memory

Each run used the full source snapshot, local Firefox, one operator, one completed sale, one skip because customer data needed updating, and a fresh copy of the same PostgreSQL 18 test database. The fixture supplied the external confirmation step. The sale raised quota from 2 to 3. The skipped customer stayed at 2. All six before/after pairs, including warm-up, matched on business files, shop receipts, operator rows and outcomes.

| Measurement | Five before readings | Five after readings | Median before → after |
| --- | --- | --- | --- |
| Start to exit, seconds | 14.258, 14.331, 13.180, 12.436, 13.537 | 13.924, 13.035, 13.251, 13.311, 13.674 | 13.537 → 13.311 |
| Python, driver and Firefox peak, MiB | 761.18, 737.83, 739.87, 742.56, 738.36 | 744.48, 743.23, 743.64, 736.55, 739.05 | 739.87 → 743.23 |
| PostgreSQL test instance peak, MiB | 528.71, 526.06, 527.63, 520.31, 525.90 | 520.74, 519.59, 525.60, 522.42, 527.50 | 526.06 → 522.42 |

The Windows sampler added the current working sets of the parent and its descendants at each reading and kept the largest sum for each process tree. Shared pages can count in more than one process. It sampled through process exit, waiting up to 150 ms between polls, with 73–80 readings per measured run. Shop startup, database seeding and final readback were outside the timer. The app's median peak rose 3.36 MiB, inside the original 23.35 MiB spread. The elapsed-time ranges also overlap. A whole-run speedup and a change in memory use for daily sales are **UNVERIFIED**.

## F111 · VERIFIED · Tests and privacy checks

Python reported `3.14.2`. The original suite printed `1447 passed in 78.77s`. The changed suite printed `1450 passed in 49.27s`, including the three new cases. Both suites ran in snapshots without operational dotenv files and with fresh local test databases. The focused run printed `80 passed in 7.71s`. It covered redaction with masking on and off, overlapping private values, Unicode digits, a custom string subclass, report readback and log output. Ruff reported `All checks passed!` and `154 files already formatted`. Mypy reported `Success: no issues found in 144 source files`. [New tests](../../tests/unit/test_privacy.py#L7) · [Existing report privacy tests](../../tests/contract/test_reporting_and_main.py#L848)

The three new tests also passed against the original implementation (`3 passed in 0.03s`), with its import path checked explicitly. All 144 candidate Python files matched the workspace after normalizing line endings. Only `src/privacy.py` and the new test file differed from the baseline. A separate offline comparison loaded `git show f03f9aa:src/privacy.py` and the workspace copy into separate Python modules. For each masking mode and three private-value registries, it compared the output type and value for every three-part combination of 17 dummy strings. The result was `PASS 29478 synthetic comparisons, both masking modes, three dummy private-value registries`.

## F112 · PARTIAL · The first diagnostic difference

In the first pair with a lasting database-write failure, the eight business files, database rows, shop receipts and failure checkpoints matched. The diagnostic comparator stopped. Only the candidate emitted one extra DEBUG event, `browser.session.cleanup_failed`, with the message `Failed to close browser context`. Database log event counts matched. The original pair is retained in `initial-goldens.log` (before run `1518800459`, after run `8d111faed0`).

The browser session emits that message if `context.close()` raises. A controlled offline check exercised the actual cleanup and logging code in both full source snapshots. A normal close produced zero cleanup errors in both. Raising the same Playwright `Error` produced exactly one identical event in both, with level DEBUG, operator `operator_01`, resource `context` and error type `Error`. The original log recorded the exception class, so the reason the browser threw it on that run is **UNVERIFIED**. The comparator still requires matching diagnostic events. [Cleanup handler](../../src/infrastructure/browser/playwright_session.py#L76) · [Cleanup regression tests](../../tests/unit/test_playwright_session.py#L235)

## F113 · VERIFIED · Reports, receipts and recovery

The full repeat used fresh dummy databases for each before/after pair and the original diagnostic comparator. It printed `PASS 7 pairs, 56 business file comparisons, both operator tables and diagnostic signatures`. Each pair matched on the complete file inventory, all eight business files byte for byte, both operator tables' schema and rows, shop receipts and the meaningful diagnostic events. The separate raw-file check also checked the expected dashboard screenshot for a lasting JSONL failure.

| Case | Matching database receipt rows, before recovery |
| --- | ---: |
| Ordinary sale | 1 |
| JSONL write fails once | 1 |
| JSONL write keeps failing | 1 |
| Database write fails once | 1 |
| Database write keeps failing | 0 |
| Customer updates, restart and skip | 5 |
| Eight ordinary routes | 8 |

Every receipt column matched. In the lasting database failure, the confirmed sale began recovery with quota 2, zero database receipts and one pending entry. Recovery produced quota 3, one receipt and zero pending entries. A second recovery gave the same result. The saved output was `[2, 0, 1] -> [3, 1, 0] ; second drain identical`. The complete repeat and the controlled check in F112 passed without changing the comparator.

**Rollback.** Revert implementation commit `9f1933d` to restore the original searches. The implementation diff was `2 files changed, 42 insertions(+), 3 deletions(-)` from `git diff --stat f03f9aa 9f1933d`. Phase 5 checks the reader guide against the current code.

## Repeating the checks

The original full source revision was `f03f9aa27b8820b0dea3bcc6a5561c7728b2289c`. The approved local fixture folder contains the two isolated source snapshots, each raw timing, the original failed diagnostic comparison, the repeat results and the database readbacks. From the repo root, these were the verification commands. The suite launcher expands to `.venv\Scripts\python.exe -B -m pytest -q --basetemp <fresh-directory>` and checks the test cluster identity before running. Use fresh suite labels and a fresh verification folder for a new comparison so earlier evidence is preserved.

```powershell
$p = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/phase4-20261124-b87a62d1'
& (Join-Path $p 'suite.ps1') reference before
& (Join-Path $p 'bench.ps1') reference baseline
& (Join-Path $p 'bench.ps1') current candidate
& (Join-Path $p 'interleaved.ps1')
& (Join-Path $p 'timings.ps1')
& (Join-Path $p 'suite.ps1') current focus tests/unit/test_privacy.py tests/unit/test_logging_utils.py tests/contract/test_reporter_aggregation.py tests/contract/test_reporting_and_main.py
& (Join-Path $p 'suite.ps1') current after
& (Join-Path $p 'pairs.ps1')
.\.venv\Scripts\python.exe -I -B (Join-Path $p 'controlled-close.py') reference
.\.venv\Scripts\python.exe -I -B (Join-Path $p 'controlled-close.py') current
.\.venv\Scripts\ruff check --no-cache .
.\.venv\Scripts\ruff format --no-cache --check .
.\.venv\Scripts\mypy .
git diff --check
```

For a **report-only comparison on another Windows machine**, the following PowerShell uses the tracked Phase 1 fixture. Run it from each clean source snapshot with the same Python 3.14.2 environment. It needs the Phase 1 document and the installed project dependencies. The fixture rejects physical writes and DB connections. Each invocation runs one warm-up and five measurements. Alternate revision order when comparing times.

```powershell
$py = (Resolve-Path '.venv/Scripts/python.exe').Path
$doc = Get-Content -Raw -Encoding UTF8 'docs/2026-11-23-phase-1-behavior-baseline.md'
$b36 = $doc.Substring($doc.IndexOf('<a id="b36"></a>'))
$start = $b36.IndexOf('import os, sys')
$code = $b36.Substring($start, $b36.IndexOf("'@ |", $start) - $start)
$import = 'from io import BytesIO, TextIOWrapper'
$adapter = @'
class MemoryBuffer(BytesIO):
    def fileno(self):
        return -12345
def virtual_fsync(fd):
    if fd != -12345:
        raise AssertionError("unexpected physical sync")
os.fsync = virtual_fsync
'@
$code = $code.Replace('BytesIO()', 'MemoryBuffer()').Replace($import, "$import`n$adapter")
$code += "`nprint('file manifest SHA256', digest)"
$masked = "set_nik_masking(True)`nfrom src.privacy import register_private_values`nregister_private_values('dummy-registered-marker')"
foreach ($variant in @($code, $code.Replace('set_nik_masking(False)', $masked))) {
    foreach ($rows in 224, 1036) {
        $variant | & $py -I -B - $rows
        if ($LASTEXITCODE) { throw 'Report benchmark failed' }
    }
}
```
