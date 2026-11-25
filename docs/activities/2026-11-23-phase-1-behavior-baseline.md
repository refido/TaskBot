# Phase 1 — What TaskBot does today

**Phase 1 complete · November 23, 2026.** The local dummy-shop baseline passed the owner-approved rule for database rows, business reports, diagnostic logs and failure screenshots. The known interrupted-write case remains documented in section 10. [Acceptance evidence](#12-phase-1-acceptance)

**Initial baseline.** The owner reports there is no practice shop. The morning run processed all 30 requested customers. The first offline checks reproduced the report files and found a failure in the existing database-sync tests. Sections 1–7 preserve the evidence that led to the repair. [Modernization plan and acceptance criteria](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure)

Reference checkout: `modernize`, commit `2e781dc673327d09c94ac8a281a9219ee5f531c9`, Python 3.14.2 on Windows (B02, B03, B08). The owner ran the shop. The original audit used saved artifacts and isolated tests. Section 8 records the subsequent source change and test-only writes.

## 1. What happened this morning

**F48 — VERIFIED in the saved reports.** The November 23 run started at 06:26:28 and ended at 06:28:40 WIB, **2 minutes 12 seconds**. Each operator processed 15 requested customer numbers (NIKs). Each has a saved persistence status of `successful`. [Run summary](../../reports/2026/11/23/20261123_062628_be17/run_meta.json) · B13, B18, B32, B46.

| Operator | Requested | Processed | Completed | Skipped | Left to process |
| --- | ---: | ---: | ---: | ---: | ---: |
| Operator 1 | 15 | 15 | 15 | 0 | 0 |
| Operator 2 | 15 | 15 | 14 | 1 | 0 |
| **Total** | **30** | **30** | **29** | **1** | **0** |

The second operator’s skip was recorded as `skipped_max_kuota` (customer quota limit). Both operators recorded zero transaction errors. For each operator, the CSV and JSONL have the same 15 rows, in the same order, with **zero differences across all 18 fields** after translating JSON values to their CSV text representation. No customer details are reproduced here. B18, B32, B46.

**F49 — VERIFIED in code and consistent with this run.** The run label was `completed_with_errors`. The account runner uses `counts.get("completed", 0) == counts["total"]` as part of its all-completed rule. A skip makes that comparison false. The error counter separately sums two error categories. The run adopts the mixed label if any operator has it. This explains how both operators can finish, persistence can report success, and the run can still have that label. `src/application/services/account_runner.py:L183-L198`, `main.py:L261-L270`; B18, B19, B22.

**C7 — PARTIAL.** The owner observed a working run, and two saved file formats agree. Independent sales-history counts, actual PostgreSQL rows and the exact revision used for the morning run are **UNVERIFIED**. The latest local summary now supersedes the November 21 snapshot cited in the earlier plan. A useful independent check would be a read-only comparison with the shop’s existing sales history for the same time window. The two aggregate counts are enough; another live sale is unnecessary for that comparison.

## 2. What “100 per operator” means for testing

**F50 — PARTIAL.** The owner reports a daily allocation of 100 stock units per operator. The history supports 100 as a useful *daily test size*. Across 162 standard run summaries, 278 operator/run entries had usable nonempty count maps. **91 of 278** recorded exactly 100 completions in one run, 178 fewer, and 9 more. When runs are summed by stored operator key and folder date, **108 of 160 operator-days (67.5%)** total exactly 100, and 11 total more than 100. B09, B18.

An operator can run more than once in a day. Those sums can include reruns or overlapping records, and they do not measure opening stock. The reason for the over-100 totals is **UNVERIFIED**. The customer loop handles an observed out-of-stock condition with `except OutOfSellableStockError` and `break`. Separately, a successful customer record gets `kuota_delta=1 if is_successful else 0`. Keep the operator’s stock and the customer’s quota separate in the test data. Preserve the observed stop rule. Adding a fixed stop at the 100th record would require a separate behavior decision. `src/orchestration/transaction_processor.py:L93-L105`, `src/infrastructure/database/operator_store.py:L293-L311`; B12, B14, B22.

## 3. What passed and what broke

| Finding | Evidence from the unchanged checkout | Meaning for Phase 1 |
| --- | --- | --- |
| **F51 — VERIFIED, test inventory and selected results** | Pytest collected **1,419** cases (1,073 unit, 306 contract, 40 integration). A focused selection passed **146** cases. These include the zero-stock stop, an unconfirmed sale, the same-NIK restart, and DB setup, cleanup and quota behavior with test doubles. B15, B23, B29–B30. | Useful offline coverage. Full-suite pass/fail remains **UNVERIFIED**. |
| **F52 — VERIFIED, existing report comparisons** | All **19** cases in the selected existing golden tests passed, including the two-operator case. The tests compare saved expected observations and hashes for seven operator files. They normalize the test root before hashing (B22, B28, B31). | The reporter matched its existing reference using a memory-backed file store. Physical disk flushing and crash recovery are still open. |
| **F53 — VERIFIED, existing test failure; high severity for the baseline** | An expanded selection of **283** cases gave **233 passed, 7 failed, 43 setup errors** (B42). The 43 setup errors report a missing `main.OperatorDatabaseManager`. A fresh-process rerun reproduced the same missing name at an import assertion (B44). Direct inspection found it in the database module and absent from `main` (B43, B45). | The focused passes above overlap this selection. Do not add their totals. The failure was present before any application change. Its effect on external callers is **UNVERIFIED**. |

One fixture calls `monkeypatch.setattr(taskbot_main.OperatorDatabaseManager, "from_env", from_env)` at `tests/contract/test_db_sync_lifecycle.py:L105-L107`. Another test asserts identity between names on `main` and on the database-sync module at `tests/unit/test_database_report_syncer.py:L235-L245`. `main.py:L19-L25` imports the syncer; the manager is imported at `src/infrastructure/database/report_syncer.py:L9-L17`. B43 also checks the setup lock and payload helper. Before repairing anything, establish which names callers relied on and whether the original test was intended to preserve that interface. Keep this failure visible in the baseline.

## 4. Two reference examples for the refactor

**F54 — VERIFIED for in-memory report bytes and prepared DB records.** We ran each example twice from an empty virtual output directory, using fixed times, fixed paths and the same made-up IDs. We used TaskBot’s reporter and DB record mapper. Each repeat compared the complete relative paths and bytes of all **14 operator files** and every field of the prepared DB records. Both repeats matched. The seven file types per operator are items CSV, items JSONL, summary, snapshot, analytics, workflow events and retries. `src/web/reporter.py:L922-L928,L1094-L1105`, `src/infrastructure/reporting/file_writer.py:L48-L92`, `src/infrastructure/database/operator_store.py:L289-L317`; B16, B22, B33–B35.

| Made-up example | Expected result | Output size | Repeat result |
| --- | --- | ---: | --- |
| 15 customers per operator, with one customer-quota skip on operator 2 | 29 completed, 1 skipped; 29 increments of one and one increment of zero | 55,400 bytes | 14 files and 30 prepared DB records identical |
| 100 customers per operator, all successful | 200 completed; 200 increments of one | 269,028 bytes | 14 files and 200 prepared DB records identical |

B35 includes the reproducible SHA-256 fingerprints. The checks also confirmed the expected row and status counts for each operator and the same customer order in CSV and JSONL. This exercise starts at the report-writing step. Actual PostgreSQL commits, pre-existing customer quota, month boundaries on a real database, run-level logs and browser artifacts still need their own comparisons. A prepared increment of one is not a readback of an updated database row.

## 5. First time and memory measurements

**F55 — VERIFIED for the local reporting workload.** These measurements include both operators’ report assembly, serialization, prepared DB records and in-memory readback checks. Each size used a fresh Python process, one warm-up and five measured runs on this machine. The memory column is the median sampled peak **working set** (memory held by the Python process), sampled every 10 ms and at the run boundaries. B36 includes every reading and the process-lifetime peak.

| Total dummy rows | Median elapsed time | Elapsed range | Median sampled peak memory | Output bytes |
| ---: | ---: | ---: | ---: | ---: |
| 224 | 207.44 ms | 205.80–211.89 ms | 45.56 MiB | 299,876 |
| 1,036 | 2,151.15 ms | 2,133.56–2,181.69 ms | 49.59 MiB | 1,323,002 |

Use B36 unchanged for a later comparison. The in-memory store includes the output bytes in process memory and omits physical disk sync. The 132-second morning run includes work outside this benchmark. Its peak memory, browser memory and database memory remain **UNVERIFIED**.

## 6. What closes Phase 1

1. **Resolve the existing test discrepancy.** Use F53 to decide whether to restore a compatibility name or revise the contract through a separate approved change. Record the full-suite result in an isolated test workspace before and after that change. One focused pass cannot stand in for it.
2. **Check real database behavior on disposable data.** With a dedicated PostgreSQL 18 test database and permission for **test-only writes**, seed fake customers with known quotas, replay a sale and a skip, and read back all columns. Include a duplicate event, an older event and a month boundary. Compare both the schema-backup layout and a fresh table. This phase performed no SQL against any database.
3. **Finish the whole-run reference without a practice shop.** A local fixture can supply business outcomes for confirmed, skipped, unclear, same-customer restart and out-of-stock cases. Record the ordered input and the expected next customer. Compare run-level files, operator files and DB rows twice from the same starting state, then measure the complete process tree with disk I/O. A local simulation can establish repeatability; independent confirmation of live sales must come from existing shop records.

**Decision.** Keep the 15-per-operator case for quick checks and the 100-per-operator case for a normal-size day. Keep current behavior unchanged while the missing test interface and the database comparison are open. No real NIKs, account credentials or production export are needed to continue with the dummy cases.

## 7. What we need next

**The next database check needs a separate local PostgreSQL test database.** The owner confirmed that both updated reference files point to the database used for daily sales. The permission for this step is SELECT only. The existing schema backup already gives us the table layout, and the offline test work below can continue without a database connection.

| Finding | Evidence | What it lets us do |
| --- | --- | --- |
| F56 · **VERIFIED** for the two supplied files | Both have the same 28 key names, two nonempty customer-list settings, and the same configured loopback host, port and database name. The five database fields expected at `src/infrastructure/database/operator_store.py:L124-L145` are populated in both. See N04 and N08. | Use them as configuration references. Their file names do not establish database isolation. The comparison prints counts and equality checks only. |
| F57 · **VERIFIED** by the owner for the database's role; current stored rows **UNVERIFIED** | The owner identified the shared target as the daily-sales database. `AGENTS.md` says “Only a local test DB.” The offline backup declares the two operator tables and their NIK primary keys at `db_query/schema backup.sql:L33,L58,L84,L93` (N01, N13). | No database session was opened and no SQL was sent. A read-only check on a separate copy can verify its PostgreSQL version, schema and the current state of dummy rows. Proof of a new quota change needs a known before/after pair. |
| F58 · **VERIFIED** in an offline diagnostic | Commit `7a9ca01` removed the old manager import from `main.py` (N07, N10, N14). Some tests still use that name and check the setup lock and payload helper at `tests/unit/test_database_report_syncer.py:L96,L115-L123,L239-L241`. In the unchanged checkout, 1 selected case passed and 20 errored. Making those three existing names available from `main` temporarily, inside a fresh test process, gave **21 passed**. Seven separate child-process tests were excluded from both runs (N12, N16, N17). | There is a specific compatibility repair to try. This experiment neither changed source files nor established that all 50 failures/errors in F53 would clear. |

**What the owner can provide**

1. **For SELECT checks:** point `.env.test` to an already prepared, separate local test database with the two operator tables and a few invented customer records. The test database can use the same PostgreSQL server with a distinct database name. Leave daily-sales settings in `.env.local`. Just say when the test copy is ready; there is no need to send a password, a real customer number or a production export.
2. **For the code repair:** give the go-ahead to change `main.py` to expose the three existing names again and rerun the affected tests. This is separate from permission to query any database. The analysis-only instruction still applies to source edits.

**While SELECT is the limit**, compare the schema and existing dummy rows. For a quota example, a synthetic before/after pair could show customer A going from 2 to 3 after one confirmed sale and customer B staying at 2 after a skip in the same month. That would support a comparison of supplied states. Verifying that TaskBot itself produces those changes would be a later write test on a disposable database, under separate authorization.

<details>
<summary>Updated configuration and offline compatibility checks (N01–N20)</summary>

**N01**

```powershell
Get-Content -LiteralPath AGENTS.md -Encoding UTF8
```

```text
- Never connect to a real/production database. Only a local test DB.
```

**N02**

```powershell
git status --short --branch --untracked-files=all
```

```text
## modernize
 M .gitignore
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

**N03**

```powershell
git rev-parse --short HEAD
```

```text
2e781dc
```

**N04**

```powershell
rg -n 'DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|DB_DATABASE|DATABASE_URL|class DatabaseConfig|def.*connect' src/infrastructure/database/operator_store.py
```

```text
126:            for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
903:    def _connect(self, database_name: str):
```

**N05**

```powershell
rg -n '^## |\*\*Decision\.|^\*\*F5[0-9]' docs/2026-11-23-phase-1-behavior-baseline.md | Select-Object -First 22
```

```text
61:## 6. What closes Phase 1
69:## Command evidence
```

**N06**

```powershell
rg -n -i 'TaskBot' 'C:\Users\user\.codex\memories\MEMORY.md' | Select-String -Pattern 'phase 1|local test database|golden baseline' | Select-Object -First 2
```

```text
(no output)
```

**N07**

```powershell
git log -n 6 --oneline -S OperatorDatabaseManager -- main.py
```

```text
7a9ca01 Add comprehensive tests for cleanup logging, precheck observation, and account processing
62e4da6 feat: Implement automatic report syncing to database after operator session
```

**N08**

```powershell
@'
import ipaddress, os, re
from pathlib import Path
from dotenv import dotenv_values
root=Path.cwd()
private=root/".env"
def ref(name):
    p=root/name
    if not p.is_file():
        print(name, "unavailable")
        return None
    if p.is_symlink() or p.resolve().parent!=root.resolve() or (private.exists() and p.samefile(private)):
        print(name, "not a separate reference file")
        return None
    data=dotenv_values(dotenv_path=p,interpolate=False,encoding="utf-8-sig")
    return {k.upper():(v or "") for k,v in data.items()}
def loopback(host):
    if host.lower().strip()=="localhost":
        return True
    try: return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError: return False
fields=("DB_HOST","DB_PORT","DB_NAME","DB_USER","DB_PASSWORD")
files={n:ref(n) for n in (".env.local",".env.test")}
for n,d in files.items():
    if d is None: continue
    present=all(d.get(k,"").strip() for k in fields)
    label=bool(re.search(r"(^|[^a-z0-9])(test|testing|sandbox|fixture|disposable)([^a-z0-9]|$)",d.get("DB_NAME",""),re.I))
    print(n, "defined keys",len(d),"all DB fields populated",present,"explicit loopback host",loopback(d.get("DB_HOST","")),"test label in DB name",label)
a,b=files.values()
if a is not None and b is not None:
    print("key sets identical",a.keys()==b.keys(),"only in local",len(a.keys()-b.keys()),"only in test",len(b.keys()-a.keys()))
    addr=("DB_HOST","DB_PORT","DB_NAME")
    if all(d.get(k,"").strip() for d in [a,b] for k in addr):
        print("same configured host/port/database",all(a[k].strip()==b[k].strip() for k in addr))
    pat=re.compile(r"^NIK(?:_\d+)?$")
    print("nonempty customer-list keys",*[sum(bool(v.strip()) for k,v in d.items() if pat.fullmatch(k)) for d in (a,b)])
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
.env.local defined keys 28 all DB fields populated True explicit loopback host True test label in DB name False
.env.test defined keys 28 all DB fields populated True explicit loopback host True test label in DB name False
key sets identical True only in local 0 only in test 0
same configured host/port/database True
nonempty customer-list keys 2 2
```

**N09**

```powershell
git log -n 1 --format='%h %ad %s' --date=short -- main.py
```

```text
838d510 2026-09-25 feat: implement environment variable loading with size constraints and update related configurations
```

**N10**

```powershell
git show --format= --unified=1 7a9ca01 -- main.py | Select-String -Pattern '^[+-].*(OperatorDatabaseManager|_database_report_payload|_DATABASE_SETUP_LOCK|DatabaseReportSyncer)' | Select-Object -First 15
```

```text
-from src.infrastructure.database import OperatorDatabaseManager
-_DATABASE_SETUP_LOCK = Lock()
-def _database_report_payload(row: Any) -> dict[str, Any]:
```

**N11**

```powershell
rg -n -A 85 '^def db_case\(' tests/contract/test_db_sync_lifecycle.py | Select-Object -Last 32
```

```text
106-    monkeypatch.setattr(taskbot_main.OperatorDatabaseManager, "from_env", from_env)
121-    path = tmp_path / "items.jsonl"
```

**N12**

```powershell
rg -n 'main\.(OperatorDatabaseManager|_DATABASE_SETUP_LOCK|_database_report_payload)|def test_setup_ready_is_per_instance_not_global' tests/unit/test_database_report_syncer.py
```

```text
96:    monkeypatch.setattr(main.OperatorDatabaseManager, "from_env", case.factory)
239:            assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
240:            assert main._DATABASE_SETUP_LOCK is report_syncer._DATABASE_SETUP_LOCK
241:            assert main._database_report_payload is report_syncer._database_report_payload
```

**N13**

```powershell
rg -n 'create table|CREATE TABLE|ADD CONSTRAINT|PRIMARY KEY' 'db_query/schema backup.sql' | Select-String -Pattern 'CREATE TABLE|PRIMARY KEY' | Select-Object -First 8
```

```text

33:CREATE TABLE public."OPERATOR_1" (
58:CREATE TABLE public."OPERATOR_2" (
84:    ADD CONSTRAINT "OPERATOR_1_pkey" PRIMARY KEY ("NIK");
93:    ADD CONSTRAINT "OPERATOR_2_pkey" PRIMARY KEY ("NIK");
```

**N14**

```powershell
git show -s --format='%h %ad %s' --date=short 7a9ca01
```

```text
7a9ca01 2026-09-15 Add comprehensive tests for cleanup logging, precheck observation, and account processing
```

**N15**

```powershell
git diff --stat
```

```text
 .gitignore | 6 +++++-
 1 file changed, 5 insertions(+), 1 deletion(-)
```

**N16**

```powershell
rg -n 'tmp_path|Path\(|\.write_text|\.exists\(|^def test_|subprocess\.run' tests/unit/test_database_report_syncer.py | Select-Object -First 30
```

```text
106:def test_main_import_constructor_and_shared_setup_lock(case):
193:def test_main_syncer_factory_remains_patchable_for_composition(monkeypatch):
223:def test_fresh_import_identity_and_no_database_initialization(first_import):
248:    result = subprocess.run(
```

**N17**

```powershell
foreach ($phaseVariant in @("checkout", "temporary-exports")) {
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def readonly(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name,(bytes,str)) and Path(os.fsdecode(name)).name.lower().startswith(".env"):
            raise PermissionError("environment reference access disabled in tests")
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
            raise PermissionError("physical write")
    if event in {"os.mkdir","os.rename","os.remove","os.rmdir","subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo"}:
        raise PermissionError(event)
sys.addaudithook(readonly)
sys.path.insert(0,str(Path.cwd()))
import psycopg2
def deny_connection(*args,**kwargs):
    raise AssertionError("unexpected database connection")
psycopg2.connect=deny_connection
import pytest, main
from src.infrastructure.database import report_syncer
mode=sys.argv[1]
if mode=="temporary-exports":
    for name in ("OperatorDatabaseManager","_DATABASE_SETUP_LOCK","_database_report_payload"):
        setattr(main,name,getattr(report_syncer,name))
from collections import Counter
class Counts:
    totals=Counter()
    def pytest_runtest_logreport(self,report):
        if report.when=="call" and report.passed: self.totals["passed"]+=1
        if report.failed: self.totals["failed" if report.when=="call" else "errors"]+=1
    def pytest_deselected(self,items):
        self.totals["deselected"]+=len(items)
result=Counts()
rc=pytest.main(["-s","--noconftest","-p","no:terminal","-p","no:logging","-p","no:cacheprovider","-k","not fresh_import_identity_and_no_database_initialization","tests/unit/test_database_report_syncer.py"],plugins=[result])
print(mode, "pytest exit", int(rc), dict(sorted(result.totals.items())))
'@ | .\.venv\Scripts\python.exe -I -B - $phaseVariant
}
```

```text
checkout pytest exit 1 {'deselected': 7, 'errors': 20, 'passed': 1}
temporary-exports pytest exit 0 {'deselected': 7, 'passed': 21}
```

**N18**

```powershell
@'
from pathlib import Path
path=Path("docs/2026-11-23-phase-1-behavior-baseline.md")
text=path.read_text(encoding="utf-8-sig")
section=text.split("\n## 7. What we need next\n",1)[1].split("<details>",1)[0]
assert all(mark in section for mark in ("F56","F57","F58","28 key names","daily-sales","21 passed","SELECT","disposable database"))
print("three findings, configuration boundary, test result and requested owner inputs verified")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
three findings, configuration boundary, test result and requested owner inputs verified
```

**N19**

```powershell
rg -n '^## 7\. What we need next|^\*\*What the owner can provide' docs/2026-11-23-phase-1-behavior-baseline.md
```

```text
69:## 7. What we need next
79:**What the owner can provide**
```

**N20** repeats N02 after the edit to check the working tree.

```text
## modernize
 M .gitignore
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

```text
check_index_coverage({"project":"D-MyProject-TaskBot","paths":["AGENTS.md","docs/2026-11-23-phase-1-behavior-baseline.md","main.py","src/infrastructure/database/operator_store.py","src/infrastructure/database/report_syncer.py","tests/unit/test_database_report_syncer.py","tests/contract/test_db_sync_lifecycle.py","db_query/schema backup.sql"]})
"freshness":"metadata_changed"
"status":"excluded"
```

The source reads and the direct comparison of the two explicitly named reference files supply the evidence.

</details>

## 8. Compatibility repair and local PostgreSQL results

**November 23 update — the approved repair passed.** The complete test suite is green. The real PostgreSQL comparison on dummy data and the comparison of physical operator files both passed. This closes the missing-import issue (F53/F58) and the database uncertainty for the restored-schema fixture (F54/F57). The previous sections record the evidence available before this repair.

| Finding | Result | Evidence |
| --- | --- | --- |
| F59 · **VERIFIED** · Separate PostgreSQL instance | PostgreSQL **18.4**, cluster `taskbot_phase1`, listening on **127.0.0.1:55432**. The data directory and encrypted test credential are under `%LOCALAPPDATA%\TaskBot\phase1-pg18`. Connections checked the cluster name, data directory, address, port, database and server major version before testing. | R23, R30–R31, R38, R42. The saved schema defines the two operator tables at `db_query/schema backup.sql:L33,L58` and their NIK primary keys at L84 and L93. |
| F60 · **VERIFIED** · Python compatibility | `main.py:L19-L24` again exposes `OperatorDatabaseManager`, `_DATABASE_SETUP_LOCK` and `_database_report_payload` from the canonical database module. Each name points to the existing object. The change adds three import lines. | R39–R45. The fresh-process identity assertions are at `tests/unit/test_database_report_syncer.py:L235-L245`. |
| F61 · **VERIFIED** · Full suite | Before: **1,368 passed, 8 failed, 43 setup errors** in 60.30 seconds. After: **1,419 passed** in 55.19 seconds, no skips or errors. The focused repair check also passed all **69** cases. The additional failure beyond F53 was a report test that used the missing payload helper. | R17, R24, R39, R41 and the [full suite output](#full-suite-output). Both runs used the same test checkout and Python environment. Only `main.py` was replaced. Suite timings are recorded for context. |
| F62 · **VERIFIED** · Committed dummy data | Two databases started from the same seeded backup schema. Independent connections read back two tables, both primary keys, 14 column definitions per table and every column of all **32 rows**. The full before/after snapshots matched. | R31, R35–R38, R42. The real persistence entry point is `src/infrastructure/database/operator_store.py:L558-L572,L594-L608`. |
| F63 · **VERIFIED** · Operator files on disk | The reporter handled 15 dummy customers per operator. It recorded **29 completions and one quota skip**. The same relative paths and raw bytes matched for all **14 files** (55,826 bytes), including empty event files. | R35, R38, R42. `src/web/reporter.py:L157-L183` configures the callback and flushes the last partial batch. |

### What the database proved

Each table started with 15 fixture customers and one extra control row. The test used the reporter’s public `complete` and `skip` methods, batches of seven and a final flush. TaskBot’s existing writer committed the batches. A fresh connection then checked the stored results. All timestamps and the report path were fixed for the comparison. R31, R35, R38, R42.

| Case | Observed result on both revisions |
| --- | --- |
| Confirmed sale within the same month | The customer’s quota went from **2 to 3**. |
| Customer-quota skip | Quota stayed at **2** and the operator file recorded the skip. |
| First confirmed sale in a new month | The customer’s quota went from **7 to 1**. |
| Same sale sent again, then an older sale event | Quota and maximum quota for the checked customer stayed at **3**. |
| A customer outside the work list | Its entire row stayed identical in each operator table. |

The SHA-256 of column definitions, primary keys and ordered rows was `aab38b1d57e7ec3e3c9a41644dbf499f11b2b60c3a9826a11a03a0adaf743043` on both runs. The report manifest hash was `693e9170e0123ef483640ce0f72efc8d7cbaa239702f0bff28d1cb2206c7c76d` on both. The test also compared the full snapshot and the actual file bytes directly. R38, R42.

### Using the test instance

| Connection setting | Value |
| --- | --- |
| Host and port | `127.0.0.1` and `55432` |
| Test database to inspect | `taskbot_phase1` |
| Test administrator | `postgres` on this separate instance |
| Other databases | `taskbot_phase1_seed` holds the unprocessed dummy starting state. `taskbot_phase1_reference` holds the original code’s results. |
| Data, server log and verification artifacts | `%LOCALAPPDATA%\TaskBot\phase1-pg18\data`, `server.log` and `verification\`. The verification directory contains the fixture script, before/after DB snapshots and both operator report trees. |

Both supplied environment references were previously confirmed to target daily sales (F56/F57). The tests used an explicit test connection and a checkout with no operational dotenv files. The cluster uses SCRAM password authentication, a credential protected by Windows for the current user, and loopback listening. This setup started PostgreSQL with `pg_ctl`. After a reboot, the same Windows user can start this instance with the following commands. R16, R22–R23, R31.

```powershell
$phaseRoot = Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$phaseBin = 'C:\Program Files\PostgreSQL\18\bin'
& "$phaseBin\pg_ctl.exe" -D "$phaseRoot\data" status
# Run the following line if the status says the test server is stopped.
& "$phaseBin\pg_ctl.exe" -D "$phaseRoot\data" -l "$phaseRoot\server.log" -w start
```

To inspect the test database, open PowerShell as the Windows user who created it. This example executes a SELECT and prints the database and table counts. R49 checks the command against the running instance.

```powershell
$phaseRoot = Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$phaseBin = 'C:\Program Files\PostgreSQL\18\bin'
$phasePassword = ConvertTo-SecureString ([IO.File]::ReadAllText("$phaseRoot\admin.dpapi"))
$previousPgPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = ([pscredential]::new('postgres',$phasePassword)).GetNetworkCredential().Password
    'SELECT current_database(), (SELECT count(*) FROM public."OPERATOR_1") AS operator_1, (SELECT count(*) FROM public."OPERATOR_2") AS operator_2;' |
        & "$phaseBin\psql.exe" -X -w -h 127.0.0.1 -p 55432 -U postgres -d taskbot_phase1 -v ON_ERROR_STOP=1
} finally {
    $env:PGPASSWORD = $previousPgPassword
}
```

**At the end of the compatibility repair**, the restored-table check covered the path from a supplied sale or skip through reports and database writes. The entry point, fresh tables, browser outputs and whole-app measurements were still open. Section 9 records the subsequent local test. Independent shop confirmation of the live run remains **UNVERIFIED**.

### Full suite output

<details>
<summary>Before · full suite</summary>

```text
........................................................................ [  5%]
........................................................................ [ 10%]
........................................................................ [ 15%]
........................................................................ [ 20%]
...........................................................EEEEEEEEEEEEE [ 25%]
EEEE.EEEFFFFFFF......................................................... [ 30%]
........................................................................ [ 35%]
........................................................................ [ 40%]
........................................................................ [ 45%]
........................................................................ [ 50%]
........................................................................ [ 55%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 71%]
........................................................................ [ 76%]
...................................EEEEEEEEEEEEEEEEE.........EEEEEE..... [ 81%]
........................................................................ [ 86%]
.........................................F.............................. [ 91%]
........................................................................ [ 96%]
...................................................                      [100%]
=================================== ERRORS ====================================
_ ERROR at setup of test_discard_logging_failure_keeps_sync_contract[bind-False] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_discard_logging_failure_keeps_sync_contract[bind-True] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_discard_logging_failure_keeps_sync_contract[exception-False] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_discard_logging_failure_keeps_sync_contract[exception-True] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
____ ERROR at setup of test_main_import_constructor_and_shared_setup_lock _____
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
______ ERROR at setup of test_lazy_reuse_file_batch_and_idempotent_close ______
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
___________ ERROR at setup of test_close_never_opened_does_nothing ____________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
______ ERROR at setup of test_early_skip_does_not_initialize[empty_rows] ______
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_early_skip_does_not_initialize[missing_report_path] __
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_configuration_result_is_cached[Missing database environment variables: DB_HOST] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
____ ERROR at setup of test_configuration_result_is_cached[invalid config] ____
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_______ ERROR at setup of test_failure_recovery_and_setup_scope[setup] ________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
________ ERROR at setup of test_failure_recovery_and_setup_scope[open] ________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_______ ERROR at setup of test_failure_recovery_and_setup_scope[batch] ________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
________ ERROR at setup of test_failure_recovery_and_setup_scope[file] ________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
__ ERROR at setup of test_closed_connection_is_replaced_without_second_close __
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
________ ERROR at setup of test_setup_ready_is_per_instance_not_global ________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_incomplete_batch_is_failure_and_discards[processed-0] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_incomplete_batch_is_failure_and_discards[inserted_or_updated-0] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_incomplete_batch_is_failure_and_discards[skipped-1] __
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
__________ ERROR at setup of test_one_off_success_lifecycle[omitted] __________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
___________ ERROR at setup of test_one_off_success_lifecycle[none] ____________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
___________ ERROR at setup of test_one_off_success_lifecycle[rows] ____________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_sync_error_discards_connection_even_in_legacy_wrapper[one] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_sync_error_discards_connection_even_in_legacy_wrapper[two] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_partial_success_can_commit_before_strict_batch_check_raises _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_repeated_wrapper_calls_have_separate_owners_and_connections _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_no_resource_paths_preserve_skip_semantics[empty_list] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_no_resource_paths_preserve_skip_semantics[empty_tuple] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_no_resource_paths_preserve_skip_semantics[disabled] __
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_no_resource_paths_preserve_skip_semantics[missing_path] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_________ ERROR at setup of test_constructor_itself_is_resource_free __________
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
__ ERROR at setup of test_constructor_failure_has_no_acquired_owner_to_close __
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_failure_before_connection_return_keeps_original_error[configuration] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_failure_before_connection_return_keeps_original_error[setup] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_failure_before_connection_return_keeps_original_error[open] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_persistent_syncer_reuses_connection_until_explicit_close _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_real_syncer_close_failure_is_logged_without_duplicate_close[False] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_real_syncer_close_failure_is_logged_without_duplicate_close[True] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_failure_after_successful_sync_still_closes_owned_connection _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_file_mode_preserves_empty_and_skipped_row_semantics[False] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_file_mode_preserves_empty_and_skipped_row_semantics[True] _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
_ ERROR at setup of test_persistent_syncer_recovers_connection_after_failed_call _
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
================================== FAILURES ===================================
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AssertionError: Traceback (most recent call last):
        File "<string>", line 14, in <module>
          assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
      AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
      
    assert 1 == 0
     +  where 1 = CompletedProcess(args=['D:\\MyProject\\TaskBot\\.venv\\Scripts\\python.exe', '-c', '\nimport sys\nfrom unittest.mock i...         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nAttributeError: module \'main\' has no attribute \'OperatorDatabaseManager\'\n').returncode
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\unit\test_database_report_syncer.py:252: AssertionError: Traceback (most recent call last):
E   AttributeError: module 'main' has no attribute '_database_report_payload'
---------------------------- Captured stderr call -----------------------------
2026-11-23T07:07:58+07:00 | INFO     | report.row_recorded | run_id=20261123_070758_a1f0 | operator_id=operator_01 | Transaction row recorded | nik="3174" | status="completed"
2026-11-23T07:07:58+07:00 | INFO     | report.files_written | run_id=20261123_070758_a1f0 | operator_id=operator_01 | Run report files written
C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\tests\contract\test_reporting_and_main.py:766: AttributeError: module 'main' has no attribute '_database_report_payload'
=========================== short test summary info ===========================
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[import src.infrastructure.database.report_syncer]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[import main]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[from main import DatabaseReportSyncer]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[from src.infrastructure.database.operator_store import OperatorDatabaseManager]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[from src.web.reporter import TransactionReporter]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[from src.application.services.account_runner import AccountRunner]
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[import src.application]
FAILED tests/contract/test_reporting_and_main.py::test_customer_identity_fields_follow_nik_through_reports_and_db_payload
ERROR tests/unit/test_database_report_syncer.py::test_discard_logging_failure_keeps_sync_contract[bind-False]
ERROR tests/unit/test_database_report_syncer.py::test_discard_logging_failure_keeps_sync_contract[bind-True]
ERROR tests/unit/test_database_report_syncer.py::test_discard_logging_failure_keeps_sync_contract[exception-False]
ERROR tests/unit/test_database_report_syncer.py::test_discard_logging_failure_keeps_sync_contract[exception-True]
ERROR tests/unit/test_database_report_syncer.py::test_main_import_constructor_and_shared_setup_lock
ERROR tests/unit/test_database_report_syncer.py::test_lazy_reuse_file_batch_and_idempotent_close
ERROR tests/unit/test_database_report_syncer.py::test_close_never_opened_does_nothing
ERROR tests/unit/test_database_report_syncer.py::test_early_skip_does_not_initialize[empty_rows]
ERROR tests/unit/test_database_report_syncer.py::test_early_skip_does_not_initialize[missing_report_path]
ERROR tests/unit/test_database_report_syncer.py::test_configuration_result_is_cached[Missing database environment variables: DB_HOST]
ERROR tests/unit/test_database_report_syncer.py::test_configuration_result_is_cached[invalid config]
ERROR tests/unit/test_database_report_syncer.py::test_failure_recovery_and_setup_scope[setup]
ERROR tests/unit/test_database_report_syncer.py::test_failure_recovery_and_setup_scope[open]
ERROR tests/unit/test_database_report_syncer.py::test_failure_recovery_and_setup_scope[batch]
ERROR tests/unit/test_database_report_syncer.py::test_failure_recovery_and_setup_scope[file]
ERROR tests/unit/test_database_report_syncer.py::test_closed_connection_is_replaced_without_second_close
ERROR tests/unit/test_database_report_syncer.py::test_setup_ready_is_per_instance_not_global
ERROR tests/unit/test_database_report_syncer.py::test_incomplete_batch_is_failure_and_discards[processed-0]
ERROR tests/unit/test_database_report_syncer.py::test_incomplete_batch_is_failure_and_discards[inserted_or_updated-0]
ERROR tests/unit/test_database_report_syncer.py::test_incomplete_batch_is_failure_and_discards[skipped-1]
ERROR tests/contract/test_db_sync_lifecycle.py::test_one_off_success_lifecycle[omitted]
ERROR tests/contract/test_db_sync_lifecycle.py::test_one_off_success_lifecycle[none]
ERROR tests/contract/test_db_sync_lifecycle.py::test_one_off_success_lifecycle[rows]
ERROR tests/contract/test_db_sync_lifecycle.py::test_sync_error_discards_connection_even_in_legacy_wrapper[one]
ERROR tests/contract/test_db_sync_lifecycle.py::test_sync_error_discards_connection_even_in_legacy_wrapper[two]
ERROR tests/contract/test_db_sync_lifecycle.py::test_partial_success_can_commit_before_strict_batch_check_raises
ERROR tests/contract/test_db_sync_lifecycle.py::test_repeated_wrapper_calls_have_separate_owners_and_connections
ERROR tests/contract/test_db_sync_lifecycle.py::test_no_resource_paths_preserve_skip_semantics[empty_list]
ERROR tests/contract/test_db_sync_lifecycle.py::test_no_resource_paths_preserve_skip_semantics[empty_tuple]
ERROR tests/contract/test_db_sync_lifecycle.py::test_no_resource_paths_preserve_skip_semantics[disabled]
ERROR tests/contract/test_db_sync_lifecycle.py::test_no_resource_paths_preserve_skip_semantics[missing_path]
ERROR tests/contract/test_db_sync_lifecycle.py::test_constructor_itself_is_resource_free
ERROR tests/contract/test_db_sync_lifecycle.py::test_constructor_failure_has_no_acquired_owner_to_close
ERROR tests/contract/test_db_sync_lifecycle.py::test_failure_before_connection_return_keeps_original_error[configuration]
ERROR tests/contract/test_db_sync_lifecycle.py::test_failure_before_connection_return_keeps_original_error[setup]
ERROR tests/contract/test_db_sync_lifecycle.py::test_failure_before_connection_return_keeps_original_error[open]
ERROR tests/contract/test_db_sync_lifecycle.py::test_persistent_syncer_reuses_connection_until_explicit_close
ERROR tests/contract/test_db_sync_lifecycle.py::test_real_syncer_close_failure_is_logged_without_duplicate_close[False]
ERROR tests/contract/test_db_sync_lifecycle.py::test_real_syncer_close_failure_is_logged_without_duplicate_close[True]
ERROR tests/contract/test_db_sync_lifecycle.py::test_failure_after_successful_sync_still_closes_owned_connection
ERROR tests/contract/test_db_sync_lifecycle.py::test_file_mode_preserves_empty_and_skipped_row_semantics[False]
ERROR tests/contract/test_db_sync_lifecycle.py::test_file_mode_preserves_empty_and_skipped_row_semantics[True]
ERROR tests/contract/test_db_sync_lifecycle.py::test_persistent_syncer_recovers_connection_after_failed_call
8 failed, 1368 passed, 43 errors in 60.30s (0:01:00)
```

</details>

<details>
<summary>After · full suite</summary>

```text
........................................................................ [  5%]
........................................................................ [ 10%]
........................................................................ [ 15%]
........................................................................ [ 20%]
........................................................................ [ 25%]
........................................................................ [ 30%]
........................................................................ [ 35%]
........................................................................ [ 40%]
........................................................................ [ 45%]
........................................................................ [ 50%]
........................................................................ [ 55%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 71%]
........................................................................ [ 76%]
........................................................................ [ 81%]
........................................................................ [ 86%]
........................................................................ [ 91%]
........................................................................ [ 96%]
...................................................                      [100%]
1419 passed in 55.19s
```

</details>

<details>
<summary>Repair, test cluster and comparison commands (R01–R52)</summary>

Commands use Windows PowerShell. No credential value is included. R22 found that this Windows build treats `--pwfile=-` as a filename. R23 used a protected temporary file and removed it after initialization. The cluster ACL required running R31/R38/R42 as the creating Windows user. R36 could not access the sandbox’s private scratch directory from that account. A separate reference checkout was made in the cluster’s verification directory. R37 compared native Windows and Git line endings. R38 verified the source with line endings accounted for before running the baseline.

**R01**

```powershell
Get-Content -LiteralPath AGENTS.md -Encoding UTF8
```

```text
- Never connect to a real/production database. Only a local test DB.
```

**R02**

```powershell
git status --short --branch --untracked-files=all
```

```text
## modernize
 M .gitignore
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

**R03**

```powershell
git rev-parse HEAD
```

```text
2e781dc673327d09c94ac8a281a9219ee5f531c9
```

**R04**

```powershell
Get-Content -LiteralPath main.py -TotalCount 55 -Encoding UTF8
```

```text
# Compatibility exports retain canonical identity and composition patch points.
```

**R05**

```powershell
rg -n 'OperatorDatabaseManager|_DATABASE_SETUP_LOCK|def _database_report_payload|__all__' src/infrastructure/database/report_syncer.py main.py
```

```text
src/infrastructure/database/report_syncer.py:9:from src.infrastructure.database.operator_store import OperatorDatabaseManager
src/infrastructure/database/report_syncer.py:21:        self._manager: OperatorDatabaseManager | None = None
src/infrastructure/database/report_syncer.py:109:    def _get_manager(self, report_path: object) -> OperatorDatabaseManager | None:
```

**R06**

```powershell
Get-Command pg_ctl.exe,initdb.exe,psql.exe -ErrorAction SilentlyContinue | Select-Object Name,Source; Get-ChildItem -LiteralPath 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name
```

```text
18
```

**R07**

```powershell
Get-Content -LiteralPath tests/integration/test_entrypoints.py -Encoding UTF8 | Select-Object -First 130
```

```text
    module = importlib.import_module("main")
    module = importlib.import_module("user_sessions")
```

**R08**

```powershell
rg -n -i 'TaskBot' 'C:\Users\user\.codex\memories\MEMORY.md' | Select-String -Pattern 'separate local|phase 1|PGDATA' | Select-Object -First 2
```

```text
(no output)
```

**R09**

```powershell
rg -n '^(CREATE|ALTER|SET |SELECT|COPY|INSERT|UPDATE|DELETE|GRANT|REVOKE|\\)' 'db_query/schema backup.sql' | ForEach-Object { $_ -replace '(restrict|unrestrict)\s+\S+', '$1 [omitted]' }
```

```text
33:CREATE TABLE public."OPERATOR_1" (
58:CREATE TABLE public."OPERATOR_2" (
```

**R10**

```powershell
Get-Content -Encoding UTF8 -LiteralPath pytest.ini; git ls-files -- '.env' '.env.*' 'reports/**' | Measure-Object | Select-Object -ExpandProperty Count
```

```text
addopts = -p no:cacheprovider
```

**R11**

```powershell
git ls-files -- '.env' '.env.*'; git ls-files | Group-Object { [IO.Path]::GetExtension($_) } | Select-Object Count,Name | Sort-Object Count -Descending | Select-Object -First 22
```

```text
.env.example
```

**R12**

```powershell
rg -n '\.goto\(|\.connect\(|https?://|connect_over_cdp' tests/integration | ForEach-Object { $_ -replace 'https?://[^\s"\x27]+','[URL]' } | Select-Object -First 25
```

```text
(no output)
```

**R13**

```powershell
Get-Item -LiteralPath 'C:\Program Files\PostgreSQL\18\bin\initdb.exe','C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' | Select-Object Name,@{n='Version';e={$_.VersionInfo.ProductVersion}}; Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\ms-playwright" -Name -ErrorAction SilentlyContinue | Select-Object -First 8; Get-Item -LiteralPath "$env:LOCALAPPDATA\TaskBot\phase1-pg18" -ErrorAction SilentlyContinue | Select-Object Name
```

```text
initdb.exe 18.4   
pg_ctl.exe 18.4   
```

**R14**

```powershell
rg -n -A 38 'def upsert_report_payload\(|def sync_report_payloads\(|def _compute|def _resolve_previous|class OperatorDatabaseManager|def _connect\(' src/infrastructure/database/operator_store.py | Select-Object -First 108
```

```text
558:    def sync_report_payloads(
```

**R15**

```powershell
rg -n 'Phase 1|N20|behavior-baseline|Working tree' docs/2026-11-23-phase-1-behavior-baseline.md | Select-Object -First 10
```

```text
1:# Phase 1 — What TaskBot does today
3:**November 23, 2026 · In progress · Application behavior change: No.** The owner reports there is no practice shop. We used the saved morning run, existing tests and made-up customer records. The morning run processed all 30 requested customers. Our local checks reproduced the report files, and also found a failure in the existing database-sync tests. **Phase 1 has started. The evidence is not yet sufficient to approve a refactor.** [Modernization plan and acceptance criteria](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure)
31:| Finding | Evidence from the unchanged checkout | Meaning for Phase 1 |
```

**R16**

```powershell
@'
import io, os, shutil, subprocess, tarfile, tempfile
from pathlib import Path
audit=Path(tempfile.mkdtemp(prefix="taskbot-p1-"))
work=audit/"checkout"
work.mkdir()
raw=subprocess.check_output(["git","archive","--format=tar","HEAD"])
copied=0
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    for item in archive:
        rel=Path(item.name)
        if not item.isfile() or rel.is_absolute() or ".." in rel.parts or rel.name.startswith(".env"):
            continue
        dest=work/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        with archive.extractfile(item) as src, dest.open("xb") as target:
            shutil.copyfileobj(src,target)
        copied+=1
print("audit_root",audit)
print("tracked files copied",copied,"private config exists",(work/".env").exists())
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
audit_root C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow
tracked files copied 145 private config exists False
```

**R17**

```powershell
@'
import os, re, subprocess, sys
from pathlib import Path
audit=Path("C:\\Users\\user\\AppData\\Local\\Temp\\taskbot-p1-tzztx6ow")
work=audit/"checkout"
stage=sys.argv[1]
env={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","PATH","PATHEXT","TEMP","TMP","USERPROFILE","LOCALAPPDATA","APPDATA","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA","USERNAME","USERDOMAIN","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","HOMEDRIVE","HOMEPATH"}}
env.update(PYTHONPATH=str(work),PYTHONDONTWRITEBYTECODE="1",PGHOST="127.0.0.1",PGPORT="1",PGDATABASE="not_in_use",PGCONNECT_TIMEOUT="1",PYTHONUTF8="1")
argv=[sys.executable,"-B","-m","pytest","-q","--tb=line","--basetemp",str(audit/("tmp-"+stage))]
log=audit/(stage+"-pytest.log")
with log.open("wb") as stream:
    proc=subprocess.run(argv,cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT)
lines=log.read_text(encoding="utf-8",errors="replace").splitlines()
print("suite",stage,"exit",proc.returncode,"log",log.name)
for line in lines[-6:]:
    if re.search(r"\b\d+ (passed|failed|errors?|skipped)\b",line): print(line[:350])
print("failed nodes",sum(x.startswith("FAILED ") for x in lines),"error nodes",sum(x.startswith("ERROR ") for x in lines))
sys.exit(proc.returncode)
'@ | .\.venv\Scripts\python.exe -I -B - before
```

```text
suite before exit 1 log before-pytest.log
8 failed, 1368 passed, 43 errors in 60.30s (0:01:00)
failed nodes 8 error nodes 43
```

**R18**

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\initdb.exe' --help | Select-String -Pattern 'pwfile|auth-host|auth-local|encoding|locale' 
```

```text
      --pwfile=FILE         read password for the new superuser from file
```

**R19**

```powershell
rg -n -A 25 'def _resolve_payload_target|def _determine|def _calculate|def _prepare|def _build_upsert|def _get_upsert|def _upsert' src/infrastructure/database/operator_store.py | Select-Object -First 112
```

```text
1116-                WHEN EXCLUDED.{updated_time} <= target.{updated_time}
1121-                WHEN EXCLUDED.{kuota} > 0
```

**R20**

```powershell
Get-Content -LiteralPath 'db_query/schema backup.sql' -Encoding UTF8 | Select-Object -Skip 32 -First 44
```

```text
CREATE TABLE public."OPERATOR_1" (
CREATE TABLE public."OPERATOR_2" (
```

**R21**

```powershell
git check-ignore -v -- .env.test .env.local
```

```text
.gitignore:175:.env.test	.env.test
.gitignore:176:.env.local	.env.local
```

**R22**

```powershell
$ErrorActionPreference = 'Stop'
$phaseBin = 'C:\Program Files\PostgreSQL\18\bin'
$phaseRoot = Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$phaseData = Join-Path $phaseRoot 'data'
if (Test-Path -LiteralPath $phaseRoot) { throw 'Instance directory already exists; initialization skipped.' }
$phasePort = 0
foreach ($candidate in 55432..55449) {
    $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
    try { $probe.Start(); $phasePort = $candidate } catch [Net.Sockets.SocketException] {} finally { $probe.Stop() }
    if ($phasePort) { break }
}
if (!$phasePort) { throw 'No unused test port in the requested range.' }
[void][IO.Directory]::CreateDirectory($phaseRoot)
$phaseSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $phaseRoot '/inheritance:r' '/grant:r' ("*{0}:(OI)(CI)F" -f $phaseSid) '*S-1-5-18:(OI)(CI)F'
if ($LASTEXITCODE) { throw 'Private directory ACL setup failed.' }
$random = [byte[]]::new(36)
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($random) } finally { $rng.Dispose() }
$phaseSecret = [Convert]::ToBase64String($random)
$secure = ConvertTo-SecureString $phaseSecret -AsPlainText -Force
[IO.File]::WriteAllText((Join-Path $phaseRoot 'admin.dpapi'), (ConvertFrom-SecureString $secure))
[IO.File]::WriteAllText((Join-Path $phaseRoot 'port.txt'), [string]$phasePort)
$phaseSecret | & (Join-Path $phaseBin 'initdb.exe') -D $phaseData -U postgres --pwfile=- -A scram-sha-256 --encoding=UTF8 --locale=C
if ($LASTEXITCODE) { throw 'initdb failed.' }
Add-Content -LiteralPath (Join-Path $phaseData 'postgresql.conf') -Encoding ASCII -Value @("listen_addresses = '127.0.0.1'", "port = $phasePort", "cluster_name = 'taskbot_phase1'", "timezone = 'Asia/Jakarta'")
& (Join-Path $phaseBin 'pg_ctl.exe') -D $phaseData -l (Join-Path $phaseRoot 'server.log') -w start
if ($LASTEXITCODE) { throw 'Test server did not start.' }
Write-Output "phase1 started on loopback port $phasePort"
```

```text
initdb: error: could not open file "-" for reading: No such file or directory
```

**R23**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$phaseData=Join-Path $phaseRoot 'data'
$phaseBin='C:\Program Files\PostgreSQL\18\bin'
if (Test-Path -LiteralPath $phaseData) { throw 'Data path already exists; inspect before retry.' }
$phasePort=[int][IO.File]::ReadAllText((Join-Path $phaseRoot 'port.txt'))
$secure=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$credential=[pscredential]::new('postgres',$secure)
$pwPath=Join-Path $phaseRoot ('init-' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($pwPath, $credential.GetNetworkCredential().Password, [Text.UTF8Encoding]::new($false))
    & (Join-Path $phaseBin 'initdb.exe') -D $phaseData -U postgres "--pwfile=$pwPath" -A scram-sha-256 --encoding=UTF8 --locale=C
    if ($LASTEXITCODE) { throw 'Test cluster initialization failed.' }
} finally { if (Test-Path -LiteralPath $pwPath) { Remove-Item -LiteralPath $pwPath } }
Add-Content -LiteralPath (Join-Path $phaseData 'postgresql.conf') -Encoding ASCII -Value @("listen_addresses = '127.0.0.1'", "port = $phasePort", "cluster_name = 'taskbot_phase1'", "timezone = 'Asia/Jakarta'")
& (Join-Path $phaseBin 'pg_ctl.exe') -D $phaseData -l (Join-Path $phaseRoot 'server.log') -w start
if ($LASTEXITCODE) { throw 'Test server did not start.' }
Write-Output "test instance port $phasePort"
```

```text
test instance port 55432
```

**R24**

```powershell
Select-String -LiteralPath 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\before-pytest.log' -Pattern '^FAILED |^E\s+' | Select-Object -Last 12 | ForEach-Object { $_.Line.Substring(0,[Math]::Min(210,$_.Line.Length)) }
```

```text
E   AttributeError: module 'main' has no attribute '_database_report_payload'
```

**R25**

```powershell
Get-Content -LiteralPath src/infrastructure/database/operator_store.py -Encoding UTF8 | Select-Object -Skip 108 -First 20; Get-Content -LiteralPath src/infrastructure/database/operator_store.py -Encoding UTF8 | Select-Object -Skip 778 -First 100
```

```text
            self._upsert_sql(normalized_table),
```

**R26**

```powershell
Get-Content -LiteralPath src/infrastructure/database/operator_store.py -Encoding UTF8 | Select-Object -Skip 1112 -First 98
```

```text
                WHEN date_trunc('month', target.{updated_time})
                     < date_trunc('month', EXCLUDED.{updated_time})
```

**R27**

```powershell
rg -n '^    def ensure_tables_exist|def .*operator_table|_CREATE|^def _parse_nik|def _get.*date' src/infrastructure/database/operator_store.py
```

```text
426:    def ensure_tables_exist(self) -> None:
920:    def _operator_table_names(self) -> tuple[str, ...]:
1366:def _parse_nik(value: Any) -> int:
```

**R28**

```powershell
Get-Content -LiteralPath src/web/reporter.py -Encoding UTF8 | Select-Object -Skip 63 -First 80; Get-Content -LiteralPath src/infrastructure/database/operator_store.py | Select-Object -Skip 151 -First 25
```

```text
class OperatorTarget:
class OperatorTargets:
```

**R29**

```powershell
Get-Content -LiteralPath src/infrastructure/database/report_syncer.py | Select-Object -Skip 193 -First 10; rg -n 'def _queue_row_for_batch_sync|def now_iso|def .*flush|def complete\(|def skip\(' src/web/reporter.py
```

```text
def _database_report_payload(row: Any) -> dict[str, Any]:
```

**R30**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
@'
import os, sys
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2 import sql
instance=Path(os.environ["LOCALAPPDATA"])/"TaskBot"/"phase1-pg18"
port=int((instance/"port.txt").read_text(encoding="ascii"))
assert 55432<=port<=55449
password=os.environ.pop("TASKBOT_P1_DB_SECRET")
def connect(name):
    if name not in {"postgres","taskbot_phase1_seed","taskbot_phase1_reference","taskbot_phase1"}: raise ValueError(name)
    conn=psycopg2.connect(host="127.0.0.1",port=port,user="postgres",password=password,dbname=name,connect_timeout=5,application_name="taskbot_phase1_check",options="-c search_path=public -c statement_timeout=30000")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('cluster_name'), current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), current_database(), current_setting('server_version_num')::int")
        label,data,addr,actual,db,version=cur.fetchone()
    assert (label,Path(data).resolve(),addr,actual,db,version//10000)==("taskbot_phase1",(instance/"data").resolve(),"127.0.0.1/32",port,name,18)
    conn.rollback()
    return conn
import subprocess
with closing(connect("postgres")) as admin:
    admin.autocommit=True
    with admin.cursor() as cur:
        cur.execute("SELECT current_setting('server_version'), current_setting('listen_addresses'), current_setting('cluster_name')")
        print("verified separate instance",cur.fetchone(),port)
        cur.execute("CREATE DATABASE taskbot_phase1_seed")
with closing(connect("taskbot_phase1_seed")) as seed:
    penv={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","PATH","TEMP","TMP","USERPROFILE","LOCALAPPDATA","APPDATA","COMSPEC"}}
    penv["PGPASSWORD"]=password
    result=subprocess.run([r"C:\Program Files\PostgreSQL\18\bin\psql.exe","-X","-w","-h","127.0.0.1","-p",str(port),"-U","postgres","-d","taskbot_phase1_seed","-v","ON_ERROR_STOP=1","--single-transaction","-f",str(Path("db_query/schema backup.sql").resolve())],env=penv,capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace")[-900:])
    with seed,seed.cursor() as cur:
        for op in (1,2):
            name="OPERATOR_"+str(op)
            query=sql.SQL('INSERT INTO {} ("NIK","OPERATOR","KUOTA","MAX_KUOTA","UPDATED_TIME","CREATED_TIME","LAST_TRANSACTION_TIME") VALUES (%s,%s,%s,%s,%s,%s,%s)').format(sql.Identifier(name))
            for i in [*range(15),99]:
                previous=op==1 and i==1
                when="2026-10-29 07:00:00" if previous else "2026-11-22 07:00:00"
                qty=7 if previous else 2
                cur.execute(query,(int(f"000000{op}{i:09}"),f"operator_{op:02}",qty,qty,when,when,when))
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name)))
            print(name,"synthetic starting rows",cur.fetchone()[0])
with closing(connect("postgres")) as admin:
    admin.autocommit=True
    with admin.cursor() as cur:
        for name in ("taskbot_phase1_reference","taskbot_phase1"):
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE taskbot_phase1_seed").format(sql.Identifier(name)))
            print("created",name)

'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
'C:\Users\user\AppData\Local\TaskBot\phase1-pg18\admin.dpapi' is denied."
```

**R31**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
@'
import os, sys
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2 import sql
instance=Path(os.environ["LOCALAPPDATA"])/"TaskBot"/"phase1-pg18"
port=int((instance/"port.txt").read_text(encoding="ascii"))
assert 55432<=port<=55449
password=os.environ.pop("TASKBOT_P1_DB_SECRET")
def connect(name):
    if name not in {"postgres","taskbot_phase1_seed","taskbot_phase1_reference","taskbot_phase1"}: raise ValueError(name)
    conn=psycopg2.connect(host="127.0.0.1",port=port,user="postgres",password=password,dbname=name,connect_timeout=5,application_name="taskbot_phase1_check",options="-c search_path=public -c statement_timeout=30000")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('cluster_name'), current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), current_database(), current_setting('server_version_num')::int")
        label,data,addr,actual,db,version=cur.fetchone()
    assert (label,Path(data).resolve(),addr,actual,db,version//10000)==("taskbot_phase1",(instance/"data").resolve(),"127.0.0.1/32",port,name,18)
    conn.rollback()
    return conn
import subprocess
with closing(connect("postgres")) as admin:
    admin.autocommit=True
    with admin.cursor() as cur:
        cur.execute("SELECT current_setting('server_version'), current_setting('listen_addresses'), current_setting('cluster_name')")
        print("verified separate instance",cur.fetchone(),port)
        cur.execute("CREATE DATABASE taskbot_phase1_seed")
with closing(connect("taskbot_phase1_seed")) as seed:
    penv={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","PATH","TEMP","TMP","USERPROFILE","LOCALAPPDATA","APPDATA","COMSPEC"}}
    penv["PGPASSWORD"]=password
    result=subprocess.run([r"C:\Program Files\PostgreSQL\18\bin\psql.exe","-X","-w","-h","127.0.0.1","-p",str(port),"-U","postgres","-d","taskbot_phase1_seed","-v","ON_ERROR_STOP=1","--single-transaction","-f",str(Path("db_query/schema backup.sql").resolve())],env=penv,capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode(errors="replace")[-900:])
    with seed,seed.cursor() as cur:
        for op in (1,2):
            name="OPERATOR_"+str(op)
            query=sql.SQL('INSERT INTO {} ("NIK","OPERATOR","KUOTA","MAX_KUOTA","UPDATED_TIME","CREATED_TIME","LAST_TRANSACTION_TIME") VALUES (%s,%s,%s,%s,%s,%s,%s)').format(sql.Identifier(name))
            for i in [*range(15),99]:
                previous=op==1 and i==1
                when="2026-10-29 07:00:00" if previous else "2026-11-22 07:00:00"
                qty=7 if previous else 2
                cur.execute(query,(int(f"000000{op}{i:09}"),f"operator_{op:02}",qty,qty,when,when,when))
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name)))
            print(name,"synthetic starting rows",cur.fetchone()[0])
with closing(connect("postgres")) as admin:
    admin.autocommit=True
    with admin.cursor() as cur:
        for name in ("taskbot_phase1_reference","taskbot_phase1"):
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE taskbot_phase1_seed").format(sql.Identifier(name)))
            print("created",name)

'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
verified separate instance ('18.4', '127.0.0.1', 'taskbot_phase1') 55432
OPERATOR_1 synthetic starting rows 16
OPERATOR_2 synthetic starting rows 16
created taskbot_phase1_reference
created taskbot_phase1
```

**R32**

```powershell
Get-Content -LiteralPath src/web/reporter.py -Encoding UTF8 | Select-Object -Skip 152 -First 88
```

```text
    def configure_batch_sync(
```

**R33**

```powershell
Get-Content -LiteralPath src/infrastructure/database/operator_store.py -Encoding UTF8 | Select-Object -Skip 593 -First 57; rg -n 'def _parse_report_datetime|def _normalize_datetime' src/infrastructure/database/operator_store.py
```

```text
            #     COMMIT
```

**R34**

```powershell
Get-Content -LiteralPath tests/contract/test_reporter_aggregation.py -Encoding UTF8 | Select-Object -Skip 18 -First 35
```

```text
def make_reporter(tmp_path, operator="operator_01"):
```

**R35**

```powershell
@'
import os, sys
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2 import sql
instance=Path(os.environ["LOCALAPPDATA"])/"TaskBot"/"phase1-pg18"
port=int((instance/"port.txt").read_text(encoding="ascii"))
assert 55432<=port<=55449
password=os.environ.pop("TASKBOT_P1_DB_SECRET")
def connect(name):
    if name not in {"postgres","taskbot_phase1_seed","taskbot_phase1_reference","taskbot_phase1"}: raise ValueError(name)
    conn=psycopg2.connect(host="127.0.0.1",port=port,user="postgres",password=password,dbname=name,connect_timeout=5,application_name="taskbot_phase1_check",options="-c search_path=public -c statement_timeout=30000")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('cluster_name'), current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), current_database(), current_setting('server_version_num')::int")
        label,data,addr,actual,db,version=cur.fetchone()
    assert (label,Path(data).resolve(),addr,actual,db,version//10000)==("taskbot_phase1",(instance/"data").resolve(),"127.0.0.1/32",port,name,18)
    conn.rollback()
    return conn

import hashlib, json, shutil
from types import SimpleNamespace
from datetime import datetime
audit=Path(__file__).resolve().parent
work=audit/"checkout"
sys.path.insert(0,str(work))
os.environ["PYTHON_DOTENV_DISABLED"]="1"
os.environ["LOGURU_AUTOINIT"]="0"
from src.infrastructure.database.operator_store import DatabaseConfig, OperatorDatabaseManager, OperatorTarget, OperatorTargets
from src.infrastructure.database import report_syncer
import src.web.reporter as reporting
import src.infrastructure.reporting.analytics as analytics
from src.privacy import set_nik_masking
stage=sys.argv[1]
assert stage in {"before","after"}
db="taskbot_phase1_reference" if stage=="before" else "taskbot_phase1"
stamp="2026-11-23T06:00:02+07:00"
start="2026-11-23T06:00:00+07:00"
class Fixed(datetime):
    @classmethod
    def now(cls,tz=None): return cls.fromisoformat(stamp)
analytics.datetime=Fixed
reporting.now_iso=lambda:stamp
reporting.log_print=lambda *args,**kw:None
set_nik_masking(False)
def snapshot(database):
    result={}
    with closing(connect(database)) as check,check.cursor() as cur:
        for table in ("OPERATOR_1","OPERATOR_2"):
            cur.execute("SELECT column_name, data_type, is_nullable, column_default, ordinal_position FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
            cols=cur.fetchall()
            cur.execute("SELECT a.attname FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey) WHERE n.nspname='public' AND t.relname=%s AND c.contype='p' ORDER BY a.attnum",(table,))
            pk=cur.fetchall()
            cur.execute(sql.SQL('SELECT * FROM {} ORDER BY "NIK"').format(sql.Identifier(table)))
            result[table]={"columns":cols,"key":pk,"rows":cur.fetchall()}
            assert len(cols)==14 and pk==[("NIK",)] and len(result[table]["rows"])==16
    return result
initial=snapshot("taskbot_phase1_seed")
assert snapshot(db)==initial
root=(audit/"report-work").resolve()
saved=(audit/("files-"+stage)).resolve()
assert root.parent==saved.parent==audit and not root.exists() and not saved.exists()
targets=OperatorTargets(tuple(OperatorTarget(f"OPERATOR_{op}",f"operator_{op:02}",operator_id=f"operator_{op:02}") for op in (1,2)))
manager=OperatorDatabaseManager(DatabaseConfig(host="127.0.0.1",port=port,name=db,user="postgres",password=password),targets)
with closing(connect(db)) as writer:
    for op in (1,2):
        rep=reporting.TransactionReporter(operator_id=f"operator_{op:02}",run_context=SimpleNamespace(run_id="phase1",started_at=start,run_dir=root))
        def persist(batch):
            result=manager.sync_report_payloads([report_syncer._database_report_payload(r) for r in batch],source="phase1-fixture",connection=writer)
            assert result.processed==len(batch) and result.inserted_or_updated==len(batch) and result.skipped==0
        rep.configure_batch_sync(persist,batch_size=7)
        for i in range(15):
            customer=f"000000{op}{i:09}"
            if (op,i)==(2,14): rep.skip(customer,start,"max_kuota")
            else: rep.complete(customer,start)
        rep.flush_pending_batches()
        rep.write_files()
        if op==1:
            replay=report_syncer._database_report_payload(rep.rows[0])
            for event in (stamp,"2026-11-01T06:00:00+07:00"):
                manager.sync_report_payloads([{**replay,"finished_at":event}],source="duplicate-or-old",connection=writer)
final=snapshot(db)
def fields(record,idx):
    return dict(zip((c[0] for c in record["columns"]),record["rows"][idx],strict=True))
for op in (1,2):
    table=f"OPERATOR_{op}"
    assert final[table]["rows"][-1]==initial[table]["rows"][-1]
    for i in range(15):
        row=fields(final[table],i)
        assert row["KUOTA"]==(1 if (op,i)==(1,1) else 2 if (op,i)==(2,14) else 3)
        if (op,i)==(1,0): assert row["MAX_KUOTA"]==3
    assert final[table]["columns"]==initial[table]["columns"]
blob=json.dumps(final,default=str,sort_keys=True,separators=(",",":")).encode()
(audit/(stage+"-db.json")).write_bytes(blob)
files={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*") if p.is_file()}
assert len(files)==14
for op in (1,2):
    path=next(k for k in files if k.endswith(f"/operator_{op:02}/items.jsonl"))
    rows=[json.loads(s) for s in files[path].splitlines()]
    assert len(rows)==15 and sum(r["status"]=="completed" for r in rows)==(15 if op==1 else 14)
manifest=json.dumps([(k,len(v),hashlib.sha256(v).hexdigest()) for k,v in sorted(files.items())],separators=(",",":")).encode()
if stage=="after":
    assert blob==(audit/"before-db.json").read_bytes()
    before=audit/"files-before"
    old={p.relative_to(before).as_posix():p.read_bytes() for p in before.rglob("*") if p.is_file()}
    assert files==old
root.rename(saved)
print(stage,"two tables, 32 rows, 14 columns each; both NIK primary keys verified")
print("same month 2->3, quota skip 2->2, new month 7->1, duplicate/older kept 3, both control rows untouched")
print("database SHA256",hashlib.sha256(blob).hexdigest())
print("operator files",len(files),"bytes",sum(map(len,files.values())),"manifest SHA256",hashlib.sha256(manifest).hexdigest())

'@ | Set-Content -LiteralPath 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\phase1-compare.py' -Encoding UTF8
```

```text
(no output)
```

**R36**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
& .\.venv\Scripts\python.exe -I -B 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\phase1-compare.py' before
```

```text
D:\MyProject\TaskBot\.venv\Scripts\python.exe: can't open file 'C:\\Users\\user\\AppData\\Local\\Temp\\taskbot-p1-tzztx6ow\\phase1-compare.py': [Errno 13] Permission denied
```

**R37**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
$phaseAudit=Join-Path $phaseRoot 'verification'
if (Test-Path -LiteralPath $phaseAudit) { throw 'Verification directory already exists.' }
[void][IO.Directory]::CreateDirectory($phaseAudit)
@'
import io, os, shutil, subprocess, tarfile, sys
from pathlib import Path
dest=Path(sys.argv[1])/"checkout"
dest.mkdir()
raw=subprocess.check_output(["git","archive","--format=tar","HEAD"])
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    for item in archive:
        rel=Path(item.name)
        if not item.isfile() or rel.is_absolute() or ".." in rel.parts or rel.name.startswith(".env"): continue
        p=dest/rel
        p.parent.mkdir(parents=True,exist_ok=True)
        with archive.extractfile(item) as src,p.open("xb") as out: shutil.copyfileobj(src,out)
assert (dest/"main.py").read_bytes()==subprocess.check_output(["git","show","HEAD:main.py"])
print("database reference checkout matches HEAD main.py")
'@ | .\.venv\Scripts\python.exe -I -B -S - $phaseAudit
if ($LASTEXITCODE) { throw 'Checkout failed.' }
@'
import os, sys
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2 import sql
instance=Path(os.environ["LOCALAPPDATA"])/"TaskBot"/"phase1-pg18"
port=int((instance/"port.txt").read_text(encoding="ascii"))
assert 55432<=port<=55449
password=os.environ.pop("TASKBOT_P1_DB_SECRET")
def connect(name):
    if name not in {"postgres","taskbot_phase1_seed","taskbot_phase1_reference","taskbot_phase1"}: raise ValueError(name)
    conn=psycopg2.connect(host="127.0.0.1",port=port,user="postgres",password=password,dbname=name,connect_timeout=5,application_name="taskbot_phase1_check",options="-c search_path=public -c statement_timeout=30000")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('cluster_name'), current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), current_database(), current_setting('server_version_num')::int")
        label,data,addr,actual,db,version=cur.fetchone()
    assert (label,Path(data).resolve(),addr,actual,db,version//10000)==("taskbot_phase1",(instance/"data").resolve(),"127.0.0.1/32",port,name,18)
    conn.rollback()
    return conn

import hashlib, json, shutil
from types import SimpleNamespace
from datetime import datetime
audit=Path(__file__).resolve().parent
work=audit/"checkout"
sys.path.insert(0,str(work))
os.environ["PYTHON_DOTENV_DISABLED"]="1"
os.environ["LOGURU_AUTOINIT"]="0"
from src.infrastructure.database.operator_store import DatabaseConfig, OperatorDatabaseManager, OperatorTarget, OperatorTargets
from src.infrastructure.database import report_syncer
import src.web.reporter as reporting
import src.infrastructure.reporting.analytics as analytics
from src.privacy import set_nik_masking
stage=sys.argv[1]
assert stage in {"before","after"}
db="taskbot_phase1_reference" if stage=="before" else "taskbot_phase1"
stamp="2026-11-23T06:00:02+07:00"
start="2026-11-23T06:00:00+07:00"
class Fixed(datetime):
    @classmethod
    def now(cls,tz=None): return cls.fromisoformat(stamp)
analytics.datetime=Fixed
reporting.now_iso=lambda:stamp
reporting.log_print=lambda *args,**kw:None
set_nik_masking(False)
def snapshot(database):
    result={}
    with closing(connect(database)) as check,check.cursor() as cur:
        for table in ("OPERATOR_1","OPERATOR_2"):
            cur.execute("SELECT column_name, data_type, is_nullable, column_default, ordinal_position FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
            cols=cur.fetchall()
            cur.execute("SELECT a.attname FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey) WHERE n.nspname='public' AND t.relname=%s AND c.contype='p' ORDER BY a.attnum",(table,))
            pk=cur.fetchall()
            cur.execute(sql.SQL('SELECT * FROM {} ORDER BY "NIK"').format(sql.Identifier(table)))
            result[table]={"columns":cols,"key":pk,"rows":cur.fetchall()}
            assert len(cols)==14 and pk==[("NIK",)] and len(result[table]["rows"])==16
    return result
initial=snapshot("taskbot_phase1_seed")
assert snapshot(db)==initial
root=(audit/"report-work").resolve()
saved=(audit/("files-"+stage)).resolve()
assert root.parent==saved.parent==audit and not root.exists() and not saved.exists()
targets=OperatorTargets(tuple(OperatorTarget(f"OPERATOR_{op}",f"operator_{op:02}",operator_id=f"operator_{op:02}") for op in (1,2)))
manager=OperatorDatabaseManager(DatabaseConfig(host="127.0.0.1",port=port,name=db,user="postgres",password=password),targets)
with closing(connect(db)) as writer:
    for op in (1,2):
        rep=reporting.TransactionReporter(operator_id=f"operator_{op:02}",run_context=SimpleNamespace(run_id="phase1",started_at=start,run_dir=root))
        def persist(batch):
            result=manager.sync_report_payloads([report_syncer._database_report_payload(r) for r in batch],source="phase1-fixture",connection=writer)
            assert result.processed==len(batch) and result.inserted_or_updated==len(batch) and result.skipped==0
        rep.configure_batch_sync(persist,batch_size=7)
        for i in range(15):
            customer=f"000000{op}{i:09}"
            if (op,i)==(2,14): rep.skip(customer,start,"max_kuota")
            else: rep.complete(customer,start)
        rep.flush_pending_batches()
        rep.write_files()
        if op==1:
            replay=report_syncer._database_report_payload(rep.rows[0])
            for event in (stamp,"2026-11-01T06:00:00+07:00"):
                manager.sync_report_payloads([{**replay,"finished_at":event}],source="duplicate-or-old",connection=writer)
final=snapshot(db)
def fields(record,idx):
    return dict(zip((c[0] for c in record["columns"]),record["rows"][idx],strict=True))
for op in (1,2):
    table=f"OPERATOR_{op}"
    assert final[table]["rows"][-1]==initial[table]["rows"][-1]
    for i in range(15):
        row=fields(final[table],i)
        assert row["KUOTA"]==(1 if (op,i)==(1,1) else 2 if (op,i)==(2,14) else 3)
        if (op,i)==(1,0): assert row["MAX_KUOTA"]==3
    assert final[table]["columns"]==initial[table]["columns"]
blob=json.dumps(final,default=str,sort_keys=True,separators=(",",":")).encode()
(audit/(stage+"-db.json")).write_bytes(blob)
files={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*") if p.is_file()}
assert len(files)==14
for op in (1,2):
    path=next(k for k in files if k.endswith(f"/operator_{op:02}/items.jsonl"))
    rows=[json.loads(s) for s in files[path].splitlines()]
    assert len(rows)==15 and sum(r["status"]=="completed" for r in rows)==(15 if op==1 else 14)
manifest=json.dumps([(k,len(v),hashlib.sha256(v).hexdigest()) for k,v in sorted(files.items())],separators=(",",":")).encode()
if stage=="after":
    assert blob==(audit/"before-db.json").read_bytes()
    before=audit/"files-before"
    old={p.relative_to(before).as_posix():p.read_bytes() for p in before.rglob("*") if p.is_file()}
    assert files==old
root.rename(saved)
print(stage,"two tables, 32 rows, 14 columns each; both NIK primary keys verified")
print("same month 2->3, quota skip 2->2, new month 7->1, duplicate/older kept 3, both control rows untouched")
print("database SHA256",hashlib.sha256(blob).hexdigest())
print("operator files",len(files),"bytes",sum(map(len,files.values())),"manifest SHA256",hashlib.sha256(manifest).hexdigest())

'@ | Set-Content -LiteralPath (Join-Path $phaseAudit 'phase1-compare.py') -Encoding UTF8
& .\.venv\Scripts\python.exe -I -B (Join-Path $phaseAudit 'phase1-compare.py') before
```

```text
AssertionError
```

**R38**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
$phaseAudit=Join-Path $phaseRoot 'verification'
@'
from pathlib import Path
import sys,subprocess
p=Path(sys.argv[1])/"checkout"/"main.py"
assert p.read_bytes().replace(b"\r\n",b"\n")==subprocess.check_output(["git","show","HEAD:main.py"]).replace(b"\r\n",b"\n")
print("verified reference main.py at HEAD with native line endings")
'@ | .\.venv\Scripts\python.exe -I -B -S - $phaseAudit
if ($LASTEXITCODE) { throw 'Reference did not match HEAD.' }
@'
import os, sys
from pathlib import Path
from contextlib import closing
import psycopg2
from psycopg2 import sql
instance=Path(os.environ["LOCALAPPDATA"])/"TaskBot"/"phase1-pg18"
port=int((instance/"port.txt").read_text(encoding="ascii"))
assert 55432<=port<=55449
password=os.environ.pop("TASKBOT_P1_DB_SECRET")
def connect(name):
    if name not in {"postgres","taskbot_phase1_seed","taskbot_phase1_reference","taskbot_phase1"}: raise ValueError(name)
    conn=psycopg2.connect(host="127.0.0.1",port=port,user="postgres",password=password,dbname=name,connect_timeout=5,application_name="taskbot_phase1_check",options="-c search_path=public -c statement_timeout=30000")
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('cluster_name'), current_setting('data_directory'), inet_server_addr()::text, inet_server_port(), current_database(), current_setting('server_version_num')::int")
        label,data,addr,actual,db,version=cur.fetchone()
    assert (label,Path(data).resolve(),addr,actual,db,version//10000)==("taskbot_phase1",(instance/"data").resolve(),"127.0.0.1/32",port,name,18)
    conn.rollback()
    return conn

import hashlib, json, shutil
from types import SimpleNamespace
from datetime import datetime
audit=Path(__file__).resolve().parent
work=audit/"checkout"
sys.path.insert(0,str(work))
os.environ["PYTHON_DOTENV_DISABLED"]="1"
os.environ["LOGURU_AUTOINIT"]="0"
from src.infrastructure.database.operator_store import DatabaseConfig, OperatorDatabaseManager, OperatorTarget, OperatorTargets
from src.infrastructure.database import report_syncer
import src.web.reporter as reporting
import src.infrastructure.reporting.analytics as analytics
from src.privacy import set_nik_masking
stage=sys.argv[1]
assert stage in {"before","after"}
db="taskbot_phase1_reference" if stage=="before" else "taskbot_phase1"
stamp="2026-11-23T06:00:02+07:00"
start="2026-11-23T06:00:00+07:00"
class Fixed(datetime):
    @classmethod
    def now(cls,tz=None): return cls.fromisoformat(stamp)
analytics.datetime=Fixed
reporting.now_iso=lambda:stamp
reporting.log_print=lambda *args,**kw:None
set_nik_masking(False)
def snapshot(database):
    result={}
    with closing(connect(database)) as check,check.cursor() as cur:
        for table in ("OPERATOR_1","OPERATOR_2"):
            cur.execute("SELECT column_name, data_type, is_nullable, column_default, ordinal_position FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
            cols=cur.fetchall()
            cur.execute("SELECT a.attname FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class t ON t.oid=c.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace JOIN pg_catalog.pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey) WHERE n.nspname='public' AND t.relname=%s AND c.contype='p' ORDER BY a.attnum",(table,))
            pk=cur.fetchall()
            cur.execute(sql.SQL('SELECT * FROM {} ORDER BY "NIK"').format(sql.Identifier(table)))
            result[table]={"columns":cols,"key":pk,"rows":cur.fetchall()}
            assert len(cols)==14 and pk==[("NIK",)] and len(result[table]["rows"])==16
    return result
initial=snapshot("taskbot_phase1_seed")
assert snapshot(db)==initial
root=(audit/"report-work").resolve()
saved=(audit/("files-"+stage)).resolve()
assert root.parent==saved.parent==audit and not root.exists() and not saved.exists()
targets=OperatorTargets(tuple(OperatorTarget(f"OPERATOR_{op}",f"operator_{op:02}",operator_id=f"operator_{op:02}") for op in (1,2)))
manager=OperatorDatabaseManager(DatabaseConfig(host="127.0.0.1",port=port,name=db,user="postgres",password=password),targets)
with closing(connect(db)) as writer:
    for op in (1,2):
        rep=reporting.TransactionReporter(operator_id=f"operator_{op:02}",run_context=SimpleNamespace(run_id="phase1",started_at=start,run_dir=root))
        def persist(batch):
            result=manager.sync_report_payloads([report_syncer._database_report_payload(r) for r in batch],source="phase1-fixture",connection=writer)
            assert result.processed==len(batch) and result.inserted_or_updated==len(batch) and result.skipped==0
        rep.configure_batch_sync(persist,batch_size=7)
        for i in range(15):
            customer=f"000000{op}{i:09}"
            if (op,i)==(2,14): rep.skip(customer,start,"max_kuota")
            else: rep.complete(customer,start)
        rep.flush_pending_batches()
        rep.write_files()
        if op==1:
            replay=report_syncer._database_report_payload(rep.rows[0])
            for event in (stamp,"2026-11-01T06:00:00+07:00"):
                manager.sync_report_payloads([{**replay,"finished_at":event}],source="duplicate-or-old",connection=writer)
final=snapshot(db)
def fields(record,idx):
    return dict(zip((c[0] for c in record["columns"]),record["rows"][idx],strict=True))
for op in (1,2):
    table=f"OPERATOR_{op}"
    assert final[table]["rows"][-1]==initial[table]["rows"][-1]
    for i in range(15):
        row=fields(final[table],i)
        assert row["KUOTA"]==(1 if (op,i)==(1,1) else 2 if (op,i)==(2,14) else 3)
        if (op,i)==(1,0): assert row["MAX_KUOTA"]==3
    assert final[table]["columns"]==initial[table]["columns"]
blob=json.dumps(final,default=str,sort_keys=True,separators=(",",":")).encode()
(audit/(stage+"-db.json")).write_bytes(blob)
files={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*") if p.is_file()}
assert len(files)==14
for op in (1,2):
    path=next(k for k in files if k.endswith(f"/operator_{op:02}/items.jsonl"))
    rows=[json.loads(s) for s in files[path].splitlines()]
    assert len(rows)==15 and sum(r["status"]=="completed" for r in rows)==(15 if op==1 else 14)
manifest=json.dumps([(k,len(v),hashlib.sha256(v).hexdigest()) for k,v in sorted(files.items())],separators=(",",":")).encode()
if stage=="after":
    assert blob==(audit/"before-db.json").read_bytes()
    before=audit/"files-before"
    old={p.relative_to(before).as_posix():p.read_bytes() for p in before.rglob("*") if p.is_file()}
    assert files==old
root.rename(saved)
print(stage,"two tables, 32 rows, 14 columns each; both NIK primary keys verified")
print("same month 2->3, quota skip 2->2, new month 7->1, duplicate/older kept 3, both control rows untouched")
print("database SHA256",hashlib.sha256(blob).hexdigest())
print("operator files",len(files),"bytes",sum(map(len,files.values())),"manifest SHA256",hashlib.sha256(manifest).hexdigest())

'@ | Set-Content -LiteralPath (Join-Path $phaseAudit 'phase1-compare.py') -Encoding UTF8
& .\.venv\Scripts\python.exe -I -B (Join-Path $phaseAudit 'phase1-compare.py') before
```

```text
verified reference main.py at HEAD with native line endings
before two tables, 32 rows, 14 columns each; both NIK primary keys verified
same month 2->3, quota skip 2->2, new month 7->1, duplicate/older kept 3, both control rows untouched
database SHA256 aab38b1d57e7ec3e3c9a41644dbf499f11b2b60c3a9826a11a03a0adaf743043
operator files 14 bytes 55826 manifest SHA256 693e9170e0123ef483640ce0f72efc8d7cbaa239702f0bff28d1cb2206c7c76d
```

**R39**

```powershell
Copy-Item -LiteralPath main.py -Destination 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\checkout\main.py' -ErrorAction Stop
@'
import os, re, subprocess, sys
from pathlib import Path
audit=Path("C:\\Users\\user\\AppData\\Local\\Temp\\taskbot-p1-tzztx6ow")
work=audit/"checkout"
stage=sys.argv[1]
env={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","PATH","PATHEXT","TEMP","TMP","USERPROFILE","LOCALAPPDATA","APPDATA","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA","USERNAME","USERDOMAIN","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","HOMEDRIVE","HOMEPATH"}}
env.update(PYTHONPATH=str(work),PYTHONDONTWRITEBYTECODE="1",PGHOST="127.0.0.1",PGPORT="1",PGDATABASE="not_in_use",PGCONNECT_TIMEOUT="1",PYTHONUTF8="1")
argv=[sys.executable,"-B","-m","pytest","-q","--tb=line","--basetemp",str(audit/("tmp-"+stage)),"tests/unit/test_database_report_syncer.py","tests/contract/test_db_sync_lifecycle.py","tests/contract/test_reporting_and_main.py::test_customer_identity_fields_follow_nik_through_reports_and_db_payload"]
log=audit/(stage+"-pytest.log")
with log.open("wb") as stream:
    proc=subprocess.run(argv,cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT)
lines=log.read_text(encoding="utf-8",errors="replace").splitlines()
print("suite",stage,"exit",proc.returncode,"log",log.name)
for line in lines[-6:]:
    if re.search(r"\b\d+ (passed|failed|errors?|skipped)\b",line): print(line[:350])
print("failed nodes",sum(x.startswith("FAILED ") for x in lines),"error nodes",sum(x.startswith("ERROR ") for x in lines))
sys.exit(proc.returncode)
'@ | .\.venv\Scripts\python.exe -I -B - focused
```

```text
suite focused exit 0 log focused-pytest.log
69 passed in 5.19s
failed nodes 0 error nodes 0
```

**R40**

```powershell
git diff --check -- main.py; git diff -- main.py
```

```text
+    _DATABASE_SETUP_LOCK as _DATABASE_SETUP_LOCK,
+    OperatorDatabaseManager as OperatorDatabaseManager,
+    _database_report_payload as _database_report_payload,
```

**R41**

```powershell
@'
import os, re, subprocess, sys
from pathlib import Path
audit=Path("C:\\Users\\user\\AppData\\Local\\Temp\\taskbot-p1-tzztx6ow")
work=audit/"checkout"
stage=sys.argv[1]
env={k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE","COMSPEC","PATH","PATHEXT","TEMP","TMP","USERPROFILE","LOCALAPPDATA","APPDATA","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA","USERNAME","USERDOMAIN","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","HOMEDRIVE","HOMEPATH"}}
env.update(PYTHONPATH=str(work),PYTHONDONTWRITEBYTECODE="1",PGHOST="127.0.0.1",PGPORT="1",PGDATABASE="not_in_use",PGCONNECT_TIMEOUT="1",PYTHONUTF8="1")
argv=[sys.executable,"-B","-m","pytest","-q","--tb=line","--basetemp",str(audit/("tmp-"+stage))]
log=audit/(stage+"-pytest.log")
with log.open("wb") as stream:
    proc=subprocess.run(argv,cwd=work,env=env,stdout=stream,stderr=subprocess.STDOUT)
lines=log.read_text(encoding="utf-8",errors="replace").splitlines()
print("suite",stage,"exit",proc.returncode,"log",log.name)
for line in lines[-6:]:
    if re.search(r"\b\d+ (passed|failed|errors?|skipped)\b",line): print(line[:350])
print("failed nodes",sum(x.startswith("FAILED ") for x in lines),"error nodes",sum(x.startswith("ERROR ") for x in lines))
sys.exit(proc.returncode)
'@ | .\.venv\Scripts\python.exe -I -B - after
```

```text
suite after exit 0 log after-pytest.log
1419 passed in 55.19s
failed nodes 0 error nodes 0
```

**R42**

```powershell
$ErrorActionPreference='Stop'
$phaseRoot=Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$sealed=ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $phaseRoot 'admin.dpapi')))
$env:TASKBOT_P1_DB_SECRET=([pscredential]::new('postgres',$sealed)).GetNetworkCredential().Password
$phaseAudit=Join-Path $phaseRoot 'verification'
$phaseMain=Join-Path $phaseAudit 'checkout\main.py'
Copy-Item -LiteralPath main.py -Destination $phaseMain -ErrorAction Stop
if ((Get-FileHash -LiteralPath main.py).Hash -ne (Get-FileHash -LiteralPath $phaseMain).Hash) { throw 'Reference checkout copy mismatch.' }
& .\.venv\Scripts\python.exe -I -B (Join-Path $phaseAudit 'phase1-compare.py') after
```

```text
after two tables, 32 rows, 14 columns each; both NIK primary keys verified
same month 2->3, quota skip 2->2, new month 7->1, duplicate/older kept 3, both control rows untouched
database SHA256 aab38b1d57e7ec3e3c9a41644dbf499f11b2b60c3a9826a11a03a0adaf743043
operator files 14 bytes 55826 manifest SHA256 693e9170e0123ef483640ce0f72efc8d7cbaa239702f0bff28d1cb2206c7c76d
```

**R43**

```powershell
git diff --stat; git status --short --branch --untracked-files=all
```

```text
 .gitignore | 6 +++++-
 main.py    | 3 +++
 2 files changed, 8 insertions(+), 1 deletion(-)
## modernize
 M .gitignore
 M main.py
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

**R44**

```powershell
rg -n '^## |^\*\*Decision\.\*\*|^Reference checkout|^\*\*November 23 decision' docs/2026-11-23-phase-1-behavior-baseline.md | Select-Object -First 13
```

```text
69:## 7. What we need next
```

**R45**

```powershell
rg -n 'as _DATABASE_SETUP_LOCK|as OperatorDatabaseManager|as _database_report_payload|^    def sync_report_payloads\(|^    def configure_batch_sync\(' main.py src/infrastructure/database/operator_store.py src/web/reporter.py
```

```text
main.py:22:    OperatorDatabaseManager as OperatorDatabaseManager,
```

**R46**

```powershell
@'
from pathlib import Path
import re
root=Path("C:\\Users\\user\\AppData\\Local\\Temp\\taskbot-p1-tzztx6ow")
for s in ("before","after"):
    data=(root/(s+"-pytest.log")).read_text(encoding="utf-8",errors="replace")
    print(s,"characters",len(data),"lines",len(data.splitlines()),"long numeric or email values",len(re.findall(r"(?<!\d)\d{16}(?!\d)|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",data)),"sensitive assignments",len(re.findall(r"(?i)(?:password|token|PGPASSWORD)\s*[:=]\s*[^\s]+",data)))
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
before characters 20601 lines 229 long numeric or email values 0 sensitive assignments 0
after characters 1622 lines 21 long numeric or email values 0 sensitive assignments 0
```

**R47**

```powershell
Get-Content -Raw -Encoding UTF8 -LiteralPath 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\before-pytest.log'
```

```text
8 failed, 1368 passed, 43 errors in 60.30s (0:01:00)
```

**R48**

```powershell
Get-Content -Raw -Encoding UTF8 -LiteralPath 'C:\Users\user\AppData\Local\Temp\taskbot-p1-tzztx6ow\after-pytest.log'
```

```text
1419 passed in 55.19s
```

**R49**

```powershell
$phaseRoot = Join-Path $env:LOCALAPPDATA 'TaskBot\phase1-pg18'
$phaseBin = 'C:\Program Files\PostgreSQL\18\bin'
$phasePassword = ConvertTo-SecureString ([IO.File]::ReadAllText("$phaseRoot\admin.dpapi"))
$previousPgPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = ([pscredential]::new('postgres',$phasePassword)).GetNetworkCredential().Password
    'SELECT current_database(), (SELECT count(*) FROM public."OPERATOR_1") AS operator_1, (SELECT count(*) FROM public."OPERATOR_2") AS operator_2;' |
        & "$phaseBin\psql.exe" -X -w -h 127.0.0.1 -p 55432 -U postgres -d taskbot_phase1 -v ON_ERROR_STOP=1
} finally {
    $env:PGPASSWORD = $previousPgPassword
}
```

```text
 current_database | operator_1 | operator_2 
------------------+------------+------------
 taskbot_phase1   |         16 |         16
(1 row)
```

**R50**

```powershell
@'
from pathlib import Path
s=Path("docs/2026-11-23-phase-1-behavior-baseline.md").read_text(encoding="utf-8-sig")
v=s.split("\n## 8. Compatibility repair and local PostgreSQL results\n",1)[1].split("\n### Full suite output\n",1)[0]
assert all(x in v for x in ("1,419 passed","8 failed, 43 setup errors","14 files","32 rows","127.0.0.1:55432","taskbot_phase1_seed"))
assert "aab38b1d57e7ec3e3c9a41644dbf499f11b2b60c3a9826a11a03a0adaf743043" in v
assert "693e9170e0123ef483640ce0f72efc8d7cbaa239702f0bff28d1cb2206c7c76d" in v
assert "1419 passed in 55.19s" in s and "8 failed, 1368 passed, 43 errors in 60.30s" in s
print("repair section, connection settings, full suite outputs and both golden hashes verified")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

**R51**

R50 returned the following result.

```text
repair section, connection settings, full suite outputs and both golden hashes verified
```

```powershell
rg -n '^## 8\. Compatibility repair|^### Using the test instance|^### Full suite output' docs/2026-11-23-phase-1-behavior-baseline.md
```

```text
407:## 8. Compatibility repair and local PostgreSQL results
433:### Using the test instance
471:### Full suite output
```

**R52**

```powershell
git diff --check -- main.py
git diff --stat -- main.py
git status --short --branch --untracked-files=all
```

```text
 main.py | 3 +++
 1 file changed, 3 insertions(+)
## modernize
 M .gitignore
 M main.py
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

The code graph search for `DatabaseReportSyncer`, `_ensure_database` and `_database_report_payload` used project `D-MyProject-TaskBot`. The inbound trace of `_database_report_payload` returned `__call__ 1`. The code snippet spanned lines 194–199. Coverage was checked for the changed files, writer, syncer, reporter, three relevant test modules, repository instructions and schema backup. Direct source reads covered excluded files.

</details>

## 9. Whole-app test in the local dummy shop

**F64 · VERIFIED for the local run.** TaskBot logged in through Firefox, looked up dummy customers, wrote reports and committed rows to a separate PostgreSQL instance. The dummy shop kept its own list of receipts. We checked that list against both TaskBot’s files and the rows read back after each process exited. All 12 processes exited with code 0. TaskBot’s own run status was `completed_with_errors` in all 12, including the small case with one sale and one quota skip. Exit code alone would have missed that distinction. W27–W31, W35, W46–W47.

The reference was commit `2e781dc`. The comparison used the same checkout with the working copy of `main.py`, which contains the three compatibility imports documented in section 8. The private copy excluded dotenv files and accepted only generated test settings. Browser requests were restricted to the dummy shop on loopback. Database connections checked the test cluster name, data directory and port `55432`. The puzzle provider supplied a fixed answer at the dummy shop’s submission step. The actual challenge and the live merchant were outside this test. Python was 3.14.2, PostgreSQL 18.4, Playwright 1.57.0 and psycopg2-binary 2.9.12. W27–W29, W42–W43, W46–W47, W52–W53. The [previous full-suite run](#full-suite-output) recorded 1,419 passes after the repair.

### What happened to each customer

**F65 · VERIFIED in all four extended runs.** Operator 1 requested six customers and finished five. Operator 2 requested one and finished one. Both operators reported successful database persistence. Each run produced three receipts and six terminal customer records. W31, W46–W47. TaskBot’s customer loop calls `self.process_single_nik(nik)` at `src/orchestration/transaction_processor.py:L97`. Its update path records `"same_nik_restart_after_update"` at line 189.

| In queue order | What the dummy shop saw | What TaskBot recorded |
| --- | --- | --- |
| Operator 1, ordinary sale | One submission, one receipt | `completed`, quota increased by one |
| Operator 1, quota already reached | Customer lookup, no submission or receipt | `skipped_max_kuota`, no quota increase |
| Operator 1, customer needs an update | One saved update, the same customer looked up twice, one submission and one receipt | One restart event, one `completed` record, quota increased once |
| Operator 1, unclear submission | One submission, no receipt | `error`, failure screenshot, no quota increase |
| Operator 1, stock runs out | Stock condition returned, no receipt | `skipped_out_of_stock`, no quota increase |
| Operator 1, next in queue | No lookup | One customer remaining, no terminal record. No new row in an empty database. The seeded customer’s quota stayed at two in the restored database. |
| Operator 2, ordinary sale | Separate login, one submission and one receipt | `completed`, quota increased by one |

### Which outputs matched

**F66 · VERIFIED for database rows and business files.** Each pair started with equal database snapshots and produced the same shop ledger. We compared column order, types, nullability, defaults, primary keys and every final row ordered by NIK. We also compared every relative file path and each file’s SHA-256 hash. The run ID, report timestamps and output root were fixed, and the operators ran one at a time. W28–W31, W35, W41, W46–W47.

| Comparison, reference against repaired copy | Final rows and schema | Files identical byte for byte | Differences |
| --- | --- | ---: | --- |
| Small case, restored database | Equal | 8 of 11 | Three diagnostic logs |
| Extended case, empty database | Equal, 5 rows in operator 1 and 1 in operator 2 | 15 of 19 | Three diagnostic logs and the unclear-sale screenshot |
| Extended case, restored database | Equal, 22 rows in operator 1 and 17 in operator 2 | 16 of 19 | Three diagnostic logs |

Each extended pair matched on `run_meta.json` and all seven files per operator: `items.csv`, `items.jsonl`, `items_snapshot.json`, `summary.json`, `analytics.json`, `workflow_events.jsonl` and `retries.jsonl`. The item CSV and JSONL agreed field by field across all 12 runs. Both database layouts had 14 columns with NIK as the primary key. Their column orders differed from one layout to the other. Fresh tables began with `OPERATOR, NIK`. Restored tables began with `NIK, OPERATOR`. A confirmed sale gave a new customer quota 1 or took the seeded customer from 2 to 3. W31, W35, W41, W46–W47.

**F67 · CONTRADICTED for the claim that every output byte repeats.** The changing files were `application.log`, `application.jsonl` and `database/database_events.jsonl`. The structured logs kept the same event order and counts. Both extended pairs had 349 application events. The fresh pair had 66 database events and the restored pair had 69. Differing fields included timestamps, elapsed time, process/thread IDs, test database names and source line numbers. The fresh pair’s two 1280 × 720 failure screenshots differed at four pixels. The restored pair’s screenshots were byte-identical. The cause of the four changed pixels is **UNVERIFIED**. The raw files are retained. W39–W41, W46, W51.

We checked that the comparison can catch a mistake. Increasing one `KUOTA` cell in an in-memory copy failed the database comparison. Changing one byte in a copy of `items.csv` flagged that file alone. The original artifacts stayed intact. W51.

### How long it took and how much memory it used

**F68 · VERIFIED for the two-customer case on this machine.** Each run used one operator, one sale, one quota skip and a new copy of the same seeded database. One warm-up preceded five measured runs. The timer covered application launch through process exit, including browser work and report and database writes. Setup of the dummy shop/database and post-run comparisons happened outside the timer. The test disabled the artificial update delay. W29, W35, W46–W47, W51.

| Measure | Five samples, in run order | Median | Range |
| --- | --- | ---: | --- |
| Wall time, seconds | 19.257, 19.022, 18.538, 19.317, 19.235 | 19.235 | 18.538–19.317 |
| Sampled app peak, MiB | 735.65, 737.80, 733.84, 735.46, 734.25 | 735.46 | 733.84–737.80 |
| Sampled PostgreSQL peak, MiB | 266.27, 252.61, 274.47, 256.88, 256.92 | 256.92 | 252.61–274.47 |
| Bytes in 11 report files | 205499, 205777, 205610, 205755, 205773 | 205755 | 205499–205777 |

The sampler summed Windows working sets at each observation, then waited 150 ms before sampling again. The app tree included Python, Node, Firefox and the console host. PostgreSQL was sampled as a separate process tree. Shared pages can count in more than one process, and brief peaks can fall between samples. The four extended runs took 70.514–75.653 seconds. Full-workday runtime and memory remain **UNVERIFIED** by this test. W29, W35, W41, W46–W47.

### What this lets us decide

**F69 · PARTIAL for C7 and Phase 1.** The local sale, skip, restart, unclear submission and stock-stop paths now have an independent result against which to check a refactor. A live sale still needs a merchant-side record that can be reconciled with a saved TaskBot result. Customer-type, consent and NIB combinations, alternate worker orders, and forced failures partway through file/database writes were outside this whole-app run. The six README routes therefore do not have six whole-app passes here. The strict all-file comparison is still open on the differences above. Keep these cases and the original artifacts when extending the safety net. See W31, W35, W39–W41, W46, W49–W51 and the [Phase 1 acceptance procedure](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure).

### How to use report history for the next tests

**F70 · VERIFIED for the saved reports.** On November 21, TaskBot recorded 200 completions and 14 skips. Among the completions, 14 had only a customer-type selection, 146 had only consent, 12 had type then consent, one had only a NIB reminder, and one had consent then a NIB reminder. The remaining 26 had no optional action recorded. Across 308 archived operator workflow files, the scan below also found 5,465 update events and 5,465 same-customer restart events. These are counts of logged events. Matching totals alone cannot prove each update led to one restart. [November 21 comparison and exact command W31](../plans/2026-11-23-plan-modernization.md#customer-path-evidence)

**Next local check.** Use those recorded sequences to choose dummy cases. Give each case a made-up customer number. For a completion, check that the dummy shop issued one receipt, TaskBot wrote one final record and PostgreSQL increased quota once. For a failed write, deliberately interrupt the test writer after the first file append or before the database commit, then inspect exactly what survived. The history does not establish the starting quota or the instant a write failed. The existing dummy shop and separate test database are sufficient for these checks. Independent proof of a particular live sale would require a separate shop-side record, such as a redacted receipt that can be matched to that run. [Local test results](#9-whole-app-test-in-the-local-dummy-shop) · [Phase 1 acceptance procedure](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure)

<details>
<summary>Command and aggregate output for the archive check</summary>

```powershell
@'
import json
from collections import Counter
from pathlib import Path
names = {"customer_type_selected": "type", "consent_continued": "consent",
         "customer_nib_reminder_continued": "NIB", "customer_update_success": "update",
         "same_nik_restart_after_update": "restart"}
files = sorted(Path("reports").glob("*/*/*/*/operators/*/workflow_events.jsonl"))
counts = Counter()
for path in files:
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                event = json.loads(line).get("event")
                if event in names:
                    counts[names[event]] += 1
print("workflow files", len(files))
print("event rows", sorted(counts.items()))
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
workflow files 308
event rows [('NIB', 169), ('consent', 7074), ('restart', 5465), ('type', 2540), ('update', 5465)]
```

</details>

### Where to find the evidence

The run evidence is on this machine in `%LOCALAPPDATA%\TaskBot\phase1-pg18\verification\whole-app-fe8bea1`. The folder contains the private test scripts, summary files and a `pass-<id>` folder for each run. Each pass has its own `shop-ledger.json`, `database.json`, `result.json`, process log and raw reports. The extended results list both revision pairs. The timing results list the warm-up first. These fixtures are local to this machine. [Small comparison](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/whole-app-fe8bea1/smoke-summary.json>) · [Extended comparisons](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/whole-app-fe8bea1/extended-summary.json>) · [Timing and memory](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/whole-app-fe8bea1/timing-summary.json>) · [Exact commands and selected output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/whole-app-fe8bea1/command-evidence.jsonl>)

W30, W31 and W35 launched the three series from the repository root with the dedicated instance’s Windows-protected test credential. The commands below are their application invocations. The command record includes the complete setup and readbacks. W42, W47 and W52 record the hashes of the private runner and reference files.

```powershell
& .\.venv\Scripts\python.exe -E -B (Join-Path $caseRoot 'series.py') smoke
& .\.venv\Scripts\python.exe -E -B (Join-Path $caseRoot 'series.py') extended
& .\.venv\Scripts\python.exe -E -B (Join-Path $caseRoot 'series.py') timing
```

W46 verified the saved outputs independently of the application process. W51 tested the comparator itself. Selected output follows.

```text
asserted smoke 2 runs and 1 golden pairs
asserted extended 4 runs and 2 golden pairs
asserted timing 6 runs and 3 golden pairs
all business comparisons passed; blocked web requests: 0
positive controls PASS: one KUOTA cell, one CSV byte; original evidence untouched
```

## 10. Customer routes and interrupted writes

**F71 · VERIFIED in the local dummy shop.** Ten whole-app runs compared the reference commit `2e781dc` with the working copy containing the three compatibility imports. Each revision ran two customer lists and three write-failure cases. Every run started with its own copy of the seeded PostgreSQL database. The shop recorded its own receipts. We compared them with the saved CSV, JSONL, summary, snapshot and independently read database rows. The app used Firefox and the same local puzzle response as section 9. All six README routes reached the expected receipt on this fixture. Live puzzle solving and merchant acceptance remain **UNVERIFIED**. H14, H18–H22, H37, H44. [Verified results for all five pairs](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/verified-final.json>)

### Which customer routes ran

| Customer list | Observed result in each revision |
| --- | --- |
| Eight customers with no update | Direct sale, type only, consent only, type then consent, NIB reminder only, consent then NIB, type then NIB, and type then consent then NIB. Each produced one receipt, one matching CSV/JSONL record and a quota change from 2 to 3. |
| Four customers needing an update | Type then consent then update, consent then update, immediate update, and type then update. In every case the shop saw one saved update, two lookups of the same customer and one receipt. Each customer had one completed record and one quota increase. |
| Close the NIB reminder, then process the next customer | Closing produced no receipt. TaskBot wrote the existing status `skipped_need updated customer data` and the customer’s quota stayed at 2. The next customer had a direct sale, one receipt and quota 3. |

Across those two lists each revision processed 14 customers and recorded 13 receipts and one skip. H22 checked the order of the shop’s actions against each scripted route. H44 reopened the raw files and checked the workflow events, both database snapshots and the receipt count for each pair. The NIB reminder is the business registration reminder. [Route comparisons](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/comparison-common.json>) · [Update and skip comparisons](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/comparison-updates.json>)

### What survived a write failure

Each test below began with one customer at quota 2. The shop issued exactly one receipt in every run. CSV and JSONL are separate item files. The snapshot is the end-of-run list of items. H22, H27, H37 and H44.

| Fault introduced in the test | What stayed on disk | Final committed quota | What TaskBot reported |
| --- | --- | ---: | --- |
| First JSONL append fails after CSV succeeds | CSV and snapshot each have one completed sale. JSONL has zero rows. | 2 | Run `completed`, persistence `successful`. The workflow log has one `post_processing_failed` event. |
| First DB write fails after updating the row but before committing | CSV, JSONL and snapshot each have one completed sale. | 3 | Run `completed`, persistence `successful`. The failed attempt rolled back. The later attempt saved the sale once. |
| Both DB write attempts fail before committing | CSV, JSONL and snapshot each have one completed sale. | 2 | Run `failed`, persistence `failed`. The application process still exited with code 0. |

**F72 · VERIFIED · high severity.** The first row is a case of false success. The account counted its only customer as processed, with zero remaining. An operator looking at the summary alone would see one completed sale and zero failures. The code appends to in-memory history, writes CSV then JSONL, and queues the database row only after both file writes return. The confirmed-sale handler catches the write exception and records a post-processing failure. This was observed on both revisions. Changing how it is reported or recovered is a separate behavior decision. Preserve the one-sale receipt as the check against accidental resubmission. H22, H27, H29, H37, H44. `src/web/reporter.py:L1094-L1106` (`self.rows.append(row)`, `self.file_writer.append_row(row)`, `self._queue_row_for_batch_sync(row)`), `src/infrastructure/reporting/file_writer.py:L57-L60` and `src/orchestration/transaction_processor.py:L445-L462`. [JSONL failure comparison](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/comparison-jsonl.json>)

**F73 · VERIFIED for the two DB faults.** After the application issued the SQL update, its connection saw quota 3 while a second connection still saw 2. After each forced rollback the second connection continued to see 2. Final readback distinguished recovery to 3 after one interruption from a final value of 2 after two interruptions. This tests the real PostgreSQL transaction boundary at `src/infrastructure/database/operator_store.py:L605-L613` (`with db_connection, db_connection.cursor() as cursor:`). H12, H22, H37, H44. [One interruption](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/comparison-db_once.json>) · [Repeated interruption](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/comparison-db_always.json>)

**F74 · VERIFIED for the seeded monthly reset.** One operator 1 customer outside the queue had last been updated on October 29. Its quota went from 7 to 0 in both normal scenarios and both DB-failure scenarios. Its maximum quota stayed at 7. In the JSONL failure scenario this other row stayed at 7, and operator 2’s table stayed identical to its starting snapshot in all five cases. The setup code calls `self.reset_monthly_quotas()` and uses a separate transaction that selects earlier months. A failed sale write can therefore coexist with a committed monthly reset. H42–H45, `src/infrastructure/database/operator_store.py:L361-L370,L493-L512`. The final verification reports queued and other quota changes separately. [Independent readback](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/verified-final.json>)

### Test results and remaining limits

**F75 · VERIFIED for the comparison between revisions.** Each of the five pairs matched on initial and final database contents, shop receipts, customer outcomes and the observations taken during the fault. Eight of eleven raw report files matched per pair for the two route lists and both DB cases. The three differing files were the text log, application JSONL log and database JSONL log. For the interrupted JSONL case, nine of twelve matched. The differences were the two application logs and the failure screenshot. The comparison retained those files. These results concern the local fixture. Matching the same bug in both versions establishes a baseline. H22, H41, H44.

- Full suite on the reference commit: `8 failed, 1368 passed, 43 errors in 67.34s`. Working copy with the previously restored imports: `1419 passed in 65.00s`. H25. [Reference suite output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/pytest-reference.log>) · [Working-copy suite output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/pytest-current.log>)
- Twelve focused existing tests passed in 0.60 seconds. They cover final sync after a file error, a failed flush, disabled database sync, cleanup and the order in which a terminal row is written. H36. [Named test results](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/pytest-focused-failures.log>)
- This pass used one operator at a time. Whole-app behavior under different worker completion orders remains **UNVERIFIED** here. The listed raw diagnostic files already differed between revisions. The monthly reset and the false-success case are separate checks to keep during a refactor. Production code and existing tests received no changes in this pass. H03, H22, H32 and the [Phase 1 acceptance procedure](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure).

The evidence folder is `%LOCALAPPDATA%\TaskBot\phase1-pg18\verification\routes-67c64cdf`. Each `pass-<id>` folder contains the independent shop ledger, both database snapshots, the process log and raw reports. The isolated execution used `matrix.py jsonl db_once db_always common updates`, and `verify-final.py` read the resulting artifacts without connecting to PostgreSQL. The working file hashes and exact commands with selected output are in the local evidence record. [Command record](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/command-evidence.jsonl>) · [Final readback script](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/routes-67c64cdf/verify-final.py>)

## 11. Worker finish order and Phase 1 results

**F76 · VERIFIED on the local dummy shop.** Both operators ran in separate worker threads. Operator 1 processed a sale and a quota skip. Operator 2 processed one sale. We ran each finish order twice on commit `2e781dc` and twice on the working copy with the three compatibility imports. That gave eight runs and 28 distinct pairs to compare. Each run started from an identical copy of the separate PostgreSQL test database. The browser used the local shop and its fixed puzzle response. The observer recorded zero blocked external browser requests. Q04–Q08, Q13–Q18, Q27. [Worker evidence](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/worker-verification.json>)

The test let both operators reach the point just before they wrote their confirmed sale. It released one operator and waited until TaskBot itself logged `account.thread.finished` before releasing the other. The application’s normal writer and database sync then ran. The test checked the shop receipts, worker thread names, application log, returned results and saved files independently. In **five of eight runs**, the first shop receipt belonged to the operator who finished second. Receipt order alone would have misidentified the finish order. Q14, Q18, Q27. The scheduler uses `for future in as_completed(future_to_operator_id)` and `results.append(result)` at `src/application/use_cases/process_account.py:L53-L66`.

| What we compared in all eight runs | Result |
| --- | --- |
| Each customer’s result | Two receipts. Each completed customer’s quota went from 2 to 3. The skipped customer stayed at 2. Both operators reported successful persistence and zero remaining customers. The run status was `completed_with_errors`. |
| PostgreSQL | Both tables matched across all 28 pairs, including column order, types, defaults, nullability, primary keys and every row. |
| Business files | All 15 files matched byte for byte across all 28 pairs: `run_meta.json` and seven files per operator. Each item CSV agreed field by field with its JSONL. |
| Worker results | The returned list followed the observed finish order. The operator list in `run_meta.json` remained in the configured order. The writer iterates `for account_config in account_configs` at `main.py:L151-L152`. |

**F77 · CONTRADICTED for exact equality of every file.** In every pair, 15 of 18 raw files matched. The differences were `application.log`, `application.jsonl` and `database/database_events.jsonl`. Each run recorded 205 structured application events and 53 structured database events. Counts by event, operator, function and log level matched across runs. Their order varied: eight observed sequences for the application log and two for the database log. The comparator retained the raw files and the first differing byte offset for each pair. This is evidence about these eight runs. Q19, Q27, Q31, Q40. [Raw comparison results](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/worker-verification.json>)

### A crashed worker, empty queues and interrupted finalization

**F78 · VERIFIED on both revisions.** Each row below ran once on each revision against a freshly created test database. The application exit code, run status and final database contents were read separately. In each case the two revisions matched on the full starting and final database snapshots, receipts, output paths and business files. Q16, Q27–Q32, Q37–Q38. [Readbacks and first differing bytes](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/boundary-verification.json>)

| Test condition | What survived | What the operator could see |
| --- | --- | --- |
| Operator 2’s worker throws before processing | Operator 1 finished its sale and quota went from 2 to 3. Operator 2 issued no receipt, wrote no operator report and its queued customer’s row stayed identical. | The run reported `failed` and logged the worker crash. Operator 2’s outcome was empty. Process exit code was 0. |
| Configured operator, empty customer list | The dummy shop recorded one login, zero lookups and zero receipts. There were zero item rows. The full database stayed identical. | Run `completed`, zero requested, processed and remaining. Exit 0. |
| No configured operators | No shop activity or operator files. The full database stayed identical. | Run `failed`, exit 1. |
| A required DB setting is absent | One receipt and one completed file row. The application made zero database connection attempts. The full database stayed identical and the queued customer remained at quota 2. | Run `completed`, persistence `successful`, with `report.db_sync.skipped` in the log. Exit 0. |
| Final `analytics.json` write raises an error | One receipt. CSV, JSONL and the item snapshot survived. The analytics file was absent and final quota was 3. | Run and persistence `failed`, with `account.report_write_error`. Exit 1. |
| Driver reports an error after releasing the persistent connection | One receipt, one completed file row and a committed quota of 3. The fixture confirmed the driver had closed the connection before it raised the error. | Run `completed`, persistence `successful`, with `report.db_connection.close_failed`. Exit 0. A connection left open by a driver failure was outside this case. |

The disabled-DB result and the interrupted JSONL write in [section 10](#10-customer-routes-and-interrupted-writes) both left the customer’s quota at 2. Their evidence differs: the disabled run wrote both item files and logged a skipped sync, while the interrupted run lost the JSONL row and logged a post-processing failure. A green persistence label alone does not establish that PostgreSQL received a sale. Q27, Q32, Q38 and H37.

**F79 · VERIFIED for one older table layout.** We created an empty disposable database with the eight column names in `tests/unit/test_operator_database.py:L791-L816`, including `NAMA`, then seeded three dummy rows. Both revisions migrated `OPERATOR_1` from 8 to 14 columns and kept NIK as the primary key. The queued sale moved from quota 2 to 3. For two unqueued control customers, the old `NAMA` value moved to `OPERATOR`. The positive-quota control inherited its update time as its last transaction time. The zero-quota control kept a null last transaction time. The complete final databases matched. This test establishes compatibility with that synthetic layout. Other historical layouts remain **UNVERIFIED**. Q34–Q38. See `src/infrastructure/database/operator_store.py:L1024-L1033` (`RENAME COLUMN`) and its backfill at lines 1075–1089. [Legacy comparison](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/boundary-verification.json>)

### Phase 1 decision

**F80 · VERIFIED for the local business baseline.** The reference is ready to use when checking future changes to receipts, operator outcomes, report files and database rows. Sections 8–11 record the full-suite checks, independent dummy-shop receipts, repeat comparisons, interrupted writes and measured time and memory. This pass added 22 whole-app runs across the two revisions. The current checkout passed **1,419 tests in 51.91 seconds**. The reference commit reproduced its previous test failures: **1,368 passed, 8 failed and 43 setup errors in 60.08 seconds**. No application code or existing tests were edited in the repository for this pass. Q04, Q17, Q27, Q38–Q40. [Reference test output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/suite-reference.log>) · [Working-copy test output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/suite-current.log>)

**At the worker-order checkpoint**, raw logs and one earlier screenshot differed across repeats. Section 12 records the owner’s subsequent decision and the completed diagnostic checks. Independent confirmation of a live sale remains **UNVERIFIED**.

The private evidence folder is `%LOCALAPPDATA%\TaskBot\phase1-pg18\verification\workers-53009644`. Each pass has its shop ledger, initial and final database snapshots, raw reports and exit code. The worker probe recorded thread arrivals and the scheduler’s own completion events. The first readback script used the operator ID as a SQL table name and stopped with a key lookup error. The corrected checker used the two actual table names and re-read the same saved artifacts. Q25, Q27. [Commands and selected outputs](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/command-evidence.jsonl>) · [Worker checker](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/verify-workers.py>) · [Boundary checker](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/workers-53009644/check-boundaries.py>)

## 12. Phase 1 acceptance

**Decision · November 23, 2026. Phase 1 is complete for the local dummy shop.** The owner approved exact matching for the database, business reports and output paths. For the three diagnostic logs, acceptance depends on the recorded events and outcomes. For failure screenshots, acceptance depends on the expected screen and its connection to the failure. This decision changes the acceptance test only. The comparison read the existing artifacts without launching TaskBot or opening a database connection. [Approved rule in the modernization plan](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure)

**F81 · VERIFIED. Database and business reports.** The checker read all 44 whole-app runs recorded in sections 9–11 and made 58 pair comparisons across 17 groups with matched inputs. All pairs matched on seed state (snapshot or saved digest), final table definitions and every row, independent shop receipts, relative file inventory, and every byte of the business files. Run metadata, operator CSV, JSON, workflow events and retries remain under exact comparison. The six timing runs compare repeats of the working copy. The other 16 groups each include the reference and working copy. A01, A05, A14–A15. [Results by fixture and run](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/acceptance-cb9407b8/result.json>)

The first comparison grouped the two smoke runs with the six timing runs. All 12 cross-series pairs differed in three business files because TaskBot saved the shop URL with port 3786 for smoke and 14730 for timing. The final check used the original smoke and timing series recorded when the runs were launched. It compared the URL bytes in full within each series. A13–A15.

**F82 · VERIFIED. Diagnostic logs.** The checker read `application.log`, `application.jsonl` and `database/database_events.jsonl` for every run. All 7,248 application events and 1,422 database events carried the run ID from their saved run metadata. It checked each scenario’s expected terminal status, receipt and item counts, successful and failed syncs, and named failures. It matched structured event counts, levels and stable business fields across repeats and checked the text log’s event, severity, run and operator against the structured application log. It also checked the order of database retries and which worker finished first. The event order of independent workers can vary. A06, A09, A11–A12, A15, A20, A22. [Acceptance checker](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/acceptance-cb9407b8/verify-acceptance.py>)

**F83 · VERIFIED. All six failure screenshots.** Each saved image opened successfully. Its path, operator, dummy customer and run matched the screenshot event and its preceding failure. Visual inspection established the following states. A08–A09, A11, A15.

| Images | What the screen showed | What established the failure |
| --- | --- | --- |
| 4 unconfirmed submissions | “Pending review” and the “KEMBALI” button | The log recorded a confirmation timeout. The dummy shop issued no receipt for that customer and the item report recorded an error. |
| 2 interrupted JSONL writes | The operator dashboard, “100 Tabung” and “Catat Penjualan” | The shop issued one receipt. After the browser returned to the dashboard, TaskBot logged a post-processing failure. The item JSONL had no sale and the quota stayed at 2 (F72). |

The saved image hashes identify the screenshots that were visually reviewed. Future runs can pass with different pixels when the screen and its failure context match. Five deliberate changes in memory were rejected: a missing log event, a changed CSV byte, a changed quota cell, a dashboard image classified as a pending submission, and a missing screenshot. A15. [Screen reviews and negative checks](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/acceptance-cb9407b8/result.json>)

**Handoff.** Phase 2 can use this baseline to check a reporting refactor. The working copy’s last full suite passed 1,419 tests (Q17, Q40). The earlier interrupted-write defect remains present, and an independent live merchant sale remains **UNVERIFIED**. No Phase 2 implementation was part of this acceptance decision.

The replay reads the archived dummy evidence. The command below runs the final checker from the repository root. [Command record with selected output](<C:/Users/user/AppData/Local/TaskBot/phase1-pg18/verification/acceptance-cb9407b8/commands.jsonl>)

```powershell
$check = Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/acceptance-cb9407b8/verify-acceptance.py'
& .\.venv\Scripts\python.exe -I -B -S $check
```

```text
44 archived runs; 17 matched fixture groups; 58 pair comparisons passed
DB, receipts, exact manifest, business file bytes, structured log signatures and text log records passed
manual screenshot confirmations: 4 pending review, 2 operator dashboard; cause and run/operator/customer link verified for each
negative controls rejected: missing event, one changed CSV byte, one changed quota, wrong reviewed screen, missing screenshot
```

## Command evidence

The commands below ran from the repository root. Each entry contains the exact shell command and selected output. Long test and benchmark commands run directly from standard input. The memory-backed files exist only inside their Python process. The fixture in B35 and B36 uses synthetic data. Useful starting points are [today’s totals](#b18), [the two repeat comparisons](#b35), [timing samples](#b36) and [the broader test result](#b42).

<details>
<summary>Open the command and output log</summary>

<a id="b01"></a>
**B01**

```powershell
Get-Content -LiteralPath AGENTS.md -Encoding UTF8
```

```text
**No claim without proof.**
```

<a id="b02"></a>
**B02**

```powershell
git status --short --branch --untracked-files=all
```

```text
## modernize
 M .gitignore
?? docs/MODERNIZATION_PLAN.md
```

<a id="b03"></a>
**B03**

```powershell
git rev-parse HEAD
```

```text
2e781dc673327d09c94ac8a281a9219ee5f531c9
```

<a id="b04"></a>
**B04**

```powershell
rg --files docs | Sort-Object
```

```text
docs\MODERNIZATION_PLAN.md
```

<a id="b05"></a>
**B05**

```powershell
rg -n -A 8 '^### Phase 1 acceptance procedure|^#### Ready to start implementation\?' docs/MODERNIZATION_PLAN.md
```

```text
399:### Phase 1 acceptance procedure
405-5. **Measure time and memory.** Start with the small correctness examples. For reporting alone, benchmark 224 and 1,036 synthetic terminal rows as archive-informed sizes. Optionally add 10,000 rows as a stress test labeled separately. Run one warm-up and five measured repetitions per size on the same machine with the same DB starting state. Record wall time, output bytes, row count, raw samples, median and range. Measure the local workflow separately. Sample the simultaneous memory use of Python and its browser/driver children throughout the run, record the sampling interval and counter, and report DB memory separately. Keep history from F31 as context. It supplies no before/after speed comparison or peak-memory baseline.
```

<a id="b06"></a>
**B06**

```powershell
rg -n -i 'TaskBot' 'C:\Users\user\.codex\memories\MEMORY.md' | Select-String -Pattern 'phase 1|test baseline|training shop|safety net' | Select-Object -First 2
```

```text
(no output)
```

<a id="b07"></a>
**B07**

```powershell
rg --files tests | Sort-Object
```

```text
tests\contract\reporter_aggregation_legacy.json
tests\contract\test_monthly_quota_lifecycle.py
tests\integration\test_transaction_confirmation.py
```

<a id="b08"></a>
**B08**

```powershell
.\.venv\Scripts\python.exe -I -B --version
```

```text
Python 3.14.2
```

<a id="b09"></a>
**B09**

```powershell
@'
from pathlib import Path
from collections import Counter, defaultdict
import json, re
root = Path("reports")
metas = sorted(p for p in root.glob("*/*/*/*/run_meta.json") if re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}",p.parent.name))
print("standard saved runs", len(metas), "latest folder date", max((p.parent.name[:8] for p in metas), default="none"))
per_day = Counter(p.parent.name[:8] for p in metas)
print("recent dates and counts", sorted(per_day.items())[-5:])
for p in metas[-1:]:
    d=json.loads(p.read_text(encoding="utf-8-sig"))
    print("run summary fields", sorted(d.keys()))
    for k in ("accounts","operators","account_results","results","summary"):
        v=d.get(k)
        if isinstance(v,list) and v and isinstance(v[0],dict): print(k, "fields", sorted(v[0]))
    for s in sorted(p.parent.glob("operators/*/summary.json"))[:1]:
        d=json.loads(s.read_text(encoding="utf-8-sig"))
        print("operator summary fields",sorted(d))
        print("nested summary fields",[(k, sorted(v.keys())[:18]) for k,v in d.items() if isinstance(v,dict) and k in {"counts","counters","totals","metrics"}])
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
standard saved runs 162 latest folder date 20261123
recent dates and counts [('20261118', 1), ('20261119', 1), ('20261120', 2), ('20261121', 1), ('20261123', 1)]
```

<a id="b10"></a>
**B10**

```powershell
rg -n '^class |^def |^    def |^from |^import ' tests/contract/test_monthly_quota_lifecycle.py tests/contract/test_database_setup_lifecycle.py | Select-Object -First 100
```

```text
tests/contract/test_database_setup_lifecycle.py:105:    def connect(**_kwargs):
tests/contract/test_database_setup_lifecycle.py:129:def test_setup_success_transaction_and_resource_lifecycle(setup_case, existing):
tests/contract/test_monthly_quota_lifecycle.py:45:def quota_case(monkeypatch):
tests/contract/test_monthly_quota_lifecycle.py:124:    def connect(**kwargs):
```

<a id="b11"></a>
**B11**

```powershell
rg -n '^class |^def |^    def |^from |^import |GOLDEN|assert actual' tests/contract/test_reporter_aggregation.py src/infrastructure/reporting/file_writer.py
```

```text
src/infrastructure/reporting/file_writer.py:57:    def append_row(self, row: TransactionRow) -> None:
tests/contract/test_reporter_aggregation.py:131:def test_legacy_outputs(frozen_reports, tmp_path, name, masked):
tests/contract/test_reporter_aggregation.py:142:    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))[key]
tests/contract/test_reporter_aggregation.py:156:    assert actual == json.loads(GOLDEN.read_text(encoding="utf-8"))[key]
```

<a id="b12"></a>
**B12**

```powershell
rg -n -i '\b100\b|stock.*limit|DAILY.*(STOCK|QUOTA)' src/infrastructure/config/settings.py src/orchestration/transaction_processor.py tests/contract/test_monthly_quota_lifecycle.py
```

```text
(no output)
```

<a id="b13"></a>
**B13**

```powershell
@'
from pathlib import Path
import json
from datetime import datetime
def layout(v):
    if isinstance(v,dict):
        return ("dict", len(v), [(k,type(x).__name__) for k,x in list(v.items())[:20] if k in {"summary","execution_status","persistence_status","counts","completed","skipped","failed","total","total_niks","operator_id","remaining_count","planned_count","error_count","elapsed_seconds"}])
    if isinstance(v,list): return ("list",len(v))
    return type(v).__name__
for p in sorted(Path("reports").glob("*/*/*/20261123_*/run_meta.json")):
    meta=json.loads(p.read_text(encoding="utf-8-sig"))
    print("run", p.parent.name, "status", meta.get("status"), "operator count", meta.get("operator_count"))
    print("elapsed seconds",(datetime.fromisoformat(meta["ended_at"])-datetime.fromisoformat(meta["started_at"])).total_seconds())
    for k in ("account_outcomes","operator_summaries","operators"):
        v=meta.get(k)
        print(k,layout(v))
        if v:
            entries = v.values() if isinstance(v,dict) else v
            first=next(iter(entries)); print("entry",layout(first))
            if isinstance(first,dict): print("entry fields",sorted(first))
    for index, s in enumerate(sorted(p.parent.glob("operators/*/summary.json")),1):
        d=json.loads(s.read_text(encoding="utf-8-sig"))
        print("operator",index,[(k,d[k] if isinstance(d[k],int) else layout(d[k])) for k in ("total_niks","completed","skipped","failed","retries","counts") if k in d])
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
run 20261123_062628_be17 status completed_with_errors operator count 2
elapsed seconds 132.0
operator 1 [('total_niks', 'str'), ('completed', 15), ('skipped', 0), ('failed', 0), ('retries', 0), ('counts', ('dict', 2, [('completed', 'int'), ('total', 'int')]))]
operator 2 [('total_niks', 'str'), ('completed', 14), ('skipped', 1), ('failed', 0), ('retries', 0), ('counts', ('dict', 3, [('completed', 'int'), ('total', 'int')]))]
```

<a id="b14"></a>
**B14**

```powershell
rg -n -i 'OutOfSellableStockError|for nik in self\.config\.nik|\bkuota_delta\b|quota_delta' src/orchestration/transaction_processor.py src/infrastructure/database/operator_store.py | Select-Object -First 22
```

```text
src/orchestration/transaction_processor.py:95:        for nik in self.config.nik:
src/orchestration/transaction_processor.py:98:            except OutOfSellableStockError as exc:
src/orchestration/transaction_processor.py:264:            except OutOfSellableStockError as exc:
src/infrastructure/database/operator_store.py:310:            kuota_delta=1 if is_successful else 0,
```

<a id="b15"></a>
**B15**

```powershell
rg -n -i '^def test_.*(older|newer|duplicate|quota|out_of_stock|restart|unconfirmed|missing_evidence)|monkeypatch\.setattr\(.*connect' tests/unit/test_operator_database.py tests/contract/test_transaction_processor.py tests/contract/test_monthly_quota_lifecycle.py tests/contract/test_database_setup_lifecycle.py | Select-Object -First 54
```

```text
tests/contract/test_database_setup_lifecycle.py:112:    monkeypatch.setattr(operator_store.psycopg2, "connect", case.connect)
tests/contract/test_transaction_processor.py:829:def test_unconfirmed_sale_never_completes_or_retries(confirmed_sale_processor, outcome):
tests/contract/test_transaction_processor.py:1403:def test_successful_update_restarts_same_nik_without_consuming_retry_budgets(
tests/contract/test_monthly_quota_lifecycle.py:131:    monkeypatch.setattr(operator_store.psycopg2, "connect", case.connect)
```

<a id="b16"></a>
**B16**

```powershell
Get-Content -LiteralPath src/infrastructure/reporting/file_writer.py -Encoding UTF8 | Select-Object -First 120
```

```text
                writer.writeheader()
        self._append_to_csv(row)
        self._append_to_jsonl(row)
            os.fsync(file_handle.fileno())
```

<a id="b17"></a>
**B17**

```powershell
rg -n -A 24 '^class TransactionRow' src/infrastructure/reporting/models.py
```

```text
22:class TransactionRow:
26-    status: str
28-    run_id: str = ""
```

<a id="b18"></a>
**B18**

```powershell
@'
from pathlib import Path
from collections import Counter, defaultdict
import json,re,csv
from datetime import datetime
runs=sorted(p for p in Path("reports").glob("*/*/*/*/run_meta.json") if re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}",p.parent.name))
buckets=Counter(); days=defaultdict(int); eligible=0; zeros=0; more=0
for m in runs:
    data=json.loads(m.read_text(encoding="utf-8-sig"))
    for op,summary in (data.get("operator_summaries") or {}).items():
        counts=summary.get("counts",{}) if isinstance(summary,dict) else {}
        if not isinstance(counts,dict) or not counts: continue
        n=counts.get("completed",0)
        if not isinstance(n,int): continue
        eligible+=1
        buckets["exactly 100" if n==100 else "below 100" if n<100 else "above 100"]+=1
        days[(m.parent.name[:8],op)]+=n
    if m.parent.name[:8]!="20261123": continue
    print("saved times", data.get("started_at"),data.get("ended_at"),"run status",data.get("status"))
    for i,(op,outcome) in enumerate(sorted(data["account_outcomes"].items()),1):
        print("operator",i,[(k,outcome.get(k)) for k in ("requested_nik_count","processed_nik_count","remaining_nik_count","execution_status","transaction_status","transaction_error_count","persistence_status")])
        base=m.parent/"operators"/op
        def category(row):
            raw=str(row.get("status",""))
            return "completed" if raw=="completed" else "skipped" if raw.startswith("skipped") else "failed" if raw.startswith("failed") else "other"
        with (base/"items.csv").open(newline="",encoding="utf-8-sig") as f: a=Counter(category(r) for r in csv.DictReader(f))
        with (base/"items.jsonl").open(encoding="utf-8-sig") as f: b=Counter(category(json.loads(s)) for s in f if s.strip())
        print("items CSV/JSONL status counts match",a==b,sorted(a.items()))
print("nonempty operator/run count maps",eligible,"by completion count",dict(sorted(buckets.items())))
print("operator/dates in these maps",len(days),"day sums exact 100",sum(n==100 for n in days.values()),"over 100",sum(n>100 for n in days.values()))
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
saved times 2026-11-23T06:26:28+07:00 2026-11-23T06:28:40+07:00 run status completed_with_errors
operator 1 [('requested_nik_count', 15), ('processed_nik_count', 15), ('remaining_nik_count', 0), ('execution_status', 'completed'), ('transaction_status', 'completed'), ('transaction_error_count', 0), ('persistence_status', 'successful')]
items CSV/JSONL status counts match True [('completed', 15)]
operator 2 [('requested_nik_count', 15), ('processed_nik_count', 15), ('remaining_nik_count', 0), ('execution_status', 'completed'), ('transaction_status', 'completed_with_errors'), ('transaction_error_count', 0), ('persistence_status', 'successful')]
items CSV/JSONL status counts match True [('completed', 14), ('skipped', 1)]
nonempty operator/run count maps 278 by completion count {'above 100': 9, 'below 100': 178, 'exactly 100': 91}
operator/dates in these maps 160 day sums exact 100 108 over 100 11
```

<a id="b19"></a>
**B19**

```powershell
rg -n 'completed_with_errors|transaction_error_count|transaction_status' main.py src/application | Select-Object -First 43
```

```text
main.py:268:    if "completed_with_errors" in statuses:
src/application\services\account_runner.py:193:            "transaction_error_count": (
```

<a id="b20"></a>
**B20**

```powershell
rg -n '^def test_|^class |psycopg2|\bconnect\(' tests/unit/test_operator_database.py tests/unit/test_database_report_payload_lifecycle.py | Select-Object -First 53
```

```text
tests/unit/test_operator_database.py:188:def test_operator_record_from_successful_report_maps_operator_and_status():
tests/unit/test_operator_database.py:256:def test_nik_parsing_skip_preserves_reason_in_operator_record_without_kuota_delta():
tests/unit/test_operator_database.py:417:def test_upsert_record_passes_expected_values_to_cursor():
```

<a id="b21"></a>
**B21**

```powershell
rg -n '^def test_|@pytest.mark.parametrize' tests/contract/test_db_sync_lifecycle.py tests/unit/test_transaction_outcome.py | Select-Object -First 45
```

```text
tests/contract/test_db_sync_lifecycle.py:170:def test_partial_success_can_commit_before_strict_batch_check_raises(db_case):
tests/unit/test_transaction_outcome.py:54:def test_missing_success_times_out_instead_of_completing(result_page):
tests/unit/test_transaction_outcome.py:80:def test_stock_empty_modal_is_a_stop_outcome(result_page):
```

<a id="b22"></a>
**B22**

```powershell
@'
from pathlib import Path
for p,a,b in [("src/application/services/account_runner.py",174,199),("main.py",257,274),("src/orchestration/transaction_processor.py",93,105),("tests/contract/test_reporter_aggregation.py",105,143)]:
    print(p)
    lines=Path(p).read_text(encoding="utf-8-sig").splitlines()
    for n in range(a,min(b,len(lines))+1): print(f"{n}: {lines[n-1]}")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
189:                 if not remaining and counts.get("completed", 0) == counts["total"]
190:                 else "completed_with_errors"
194:                 counts.get("error", 0) + counts.get("failed_puzzle_solve", 0)
124:         files[attr] = hashlib.sha256(content.encode("utf-8")).hexdigest()
```

<a id="b23"></a>
**B23**

```powershell
rg -n '^def test_.*(stock|retry|restart|unconfirmed_sale|terminal_skip)' tests/contract/test_transaction_processor.py | Select-Object -First 45
```

```text
441:def test_dashboard_zero_stock_records_one_terminal_row_before_stopping():
829:def test_unconfirmed_sale_never_completes_or_retries(confirmed_sale_processor, outcome):
1403:def test_successful_update_restarts_same_nik_without_consuming_retry_budgets(
1481:def test_repeated_update_after_same_nik_restart_is_terminal_without_retry():
```

<a id="b24"></a>
**B24**

```powershell
rg -n 'def db_case|tmp_path|open\(' tests/contract/test_db_sync_lifecycle.py tests/contract/test_database_setup_lifecycle.py tests/contract/test_monthly_quota_lifecycle.py tests/unit/test_database_report_payload_lifecycle.py
```

```text
tests/contract/test_db_sync_lifecycle.py:43:def db_case(monkeypatch, tmp_path):
tests/contract/test_db_sync_lifecycle.py:121:    path = tmp_path / "items.jsonl"
```

<a id="b25"></a>
**B25**

```powershell
rg -n 'def .*|MASK' src/privacy.py | Select-Object -First 30
```

```text
19:def set_nik_masking(enabled: bool) -> None:
41:def display_nik(value: object) -> str:
```

<a id="b26"></a>
**B26**

```powershell
.\.venv\Scripts\python.exe -I -B -c "from importlib.util import find_spec; print({k: bool(find_spec(k)) for k in ('pyfakefs', 'fsspec', 'psutil', 'pytest')})"
```

```text
{'pyfakefs': False, 'fsspec': False, 'psutil': False, 'pytest': True}
```

<a id="b27"></a>
**B27**

```powershell
rg -n '\.(open|touch|mkdir|replace|rename|glob|exists|is_dir|stat|write_text)\(|\bopen\(' src/web/reporter.py src/infrastructure/reporting/file_writer.py | Select-Object -First 60
```

```text
src/web/reporter.py:143:        if not self.jsonl_path.exists():
src/web/reporter.py:145:        if not self.workflow_events_path.exists():
src/web/reporter.py:920:        self.run_dir.mkdir(parents=True, exist_ok=True)
src/infrastructure/reporting/file_writer.py:74:        with self.csv_path.open("a", newline="", encoding="utf-8") as file_handle:
```

<a id="b28"></a>
**B28**

```powershell
@'
from pathlib import Path
p=Path("tests/contract/test_reporter_aggregation.py")
s=p.read_text(encoding="utf-8").splitlines()
for n in [*range(40,58), *range(144,158)]:
    print(f"{n}: {s[n-1]}")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
41:     monkeypatch.setattr(reporting, "now_iso", lambda: END)
48: def make_reporter(tmp_path, operator="operator_01"):
52:             run_id="fixed_run", started_at=START, run_dir=tmp_path / "fixed_run"
148:         first.record_retry(str(i), process=f"process{i % 2}", trigger=f"trigger{i % 2}",
152:     first._record_row(dataset("single")[0])
```

<a id="b29"></a>
**B29**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class Count:
    def pytest_collection_finish(self, session):
        from collections import Counter
        bins=Counter(Path(i.path).parent.name for i in session.items)
        print("inventory:", sorted(bins.items()), "total",len(session.items))
raise SystemExit(pytest.main([*opts,"--collect-only","-qq"], plugins=[Count()]))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
inventory: [('contract', 306), ('integration', 40), ('unit', 1073)] total 1419
```

<a id="b30"></a>
**B30**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
chosen=[
    "tests/contract/test_database_setup_lifecycle.py",
    "tests/contract/test_monthly_quota_lifecycle.py",
    "tests/unit/test_database_report_payload_lifecycle.py",
    "tests/unit/test_transaction_outcome.py",
    "tests/unit/test_operator_database.py::test_operator_record_from_successful_report_maps_operator_and_status",
    "tests/unit/test_operator_database.py::test_nik_parsing_skip_preserves_reason_in_operator_record_without_kuota_delta",
    "tests/unit/test_operator_database.py::test_upsert_record_passes_expected_values_to_cursor",
    "tests/contract/test_transaction_processor.py::test_dashboard_zero_stock_records_one_terminal_row_before_stopping",
    "tests/contract/test_transaction_processor.py::test_unconfirmed_sale_never_completes_or_retries",
    "tests/contract/test_transaction_processor.py::test_successful_update_restarts_same_nik_without_consuming_retry_budgets",
    "tests/contract/test_transaction_processor.py::test_repeated_update_after_same_nik_restart_is_terminal_without_retry",
    "tests/unit/test_customer_workflow.py::test_requested_happy_customer_path_matrix",
]
raise SystemExit(pytest.main([*opts,*chosen]))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
..................................................................................................................................................
146 passed in 0.78s
```

<a id="b31"></a>
**B31**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class TempInMemory:
    @pytest.fixture
    def tmp_path(self):
        with MemoryFiles().active():
            yield ROOT
mod="tests/contract/test_reporter_aggregation.py::"
raise SystemExit(pytest.main([*opts, mod+"test_legacy_outputs", mod+"test_two_operator_event_outputs"], plugins=[TempInMemory()]))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
...................
19 passed in 0.38s
```

<a id="b32"></a>
**B32**

```powershell
@'
from pathlib import Path
import json
for m in sorted(Path("reports").glob("*/*/*/20261123_*/run_meta.json")):
    kinds=set()
    for file in sorted(m.parent.glob("operators/*/items.jsonl")):
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            status=str(json.loads(line).get("status",""))
            if status.startswith("skipped"):
                categories={"skipped_out_of_stock": "no sellable stock", "skipped_max_kuota": "customer quota limit", "skipped_not_registered": "customer unregistered", "skipped_cannot_transact": "customer cannot transact", "skipped_registration_request_limited":"registration limit", "skipped_nik is not yet 17 years old":"under age threshold"}
                kinds.add(categories.get(status,"other recorded skip"))
    print("skip category", sorted(kinds))

'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
skip category ['customer quota limit']
```

<a id="b33"></a>
**B33**

```powershell
rg -n -A 20 '^class OperatorRecord|def from_report_payload|def _record_row\(' src/infrastructure/database/operator_store.py src/web/reporter.py | Select-Object -First 68
```

```text
src/infrastructure/database/operator_store.py-295-        is_successful = status in _SUCCESS_STATUSES
src/web/reporter.py:1094:    def _record_row(self, row: TransactionRow) -> None:
src/web/reporter.py-1095-        self.rows.append(row)
src/web/reporter.py-1097-            self.file_writer.append_row(row)
```

<a id="b34"></a>
**B34**

```powershell
@'
from pathlib import Path
p=Path("src/infrastructure/database/operator_store.py")
s=p.read_text(encoding="utf-8").splitlines()
for i,line in enumerate(s,1):
    if line.startswith("class OperatorTarget"):
        for j in range(i,i+11): print(f"{j}: {s[j-1]}")
    if 274<=i<=282 or 305<=i<=322: print(f"{i}: {line}")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
153: class OperatorTarget:
276: class OperatorDbRecord:
310:             kuota_delta=1 if is_successful else 0,
311:             status_code=status_mapping.status_code,
```

<a id="b35"></a>
**B35**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
from collections import Counter
from dataclasses import asdict
import csv, hashlib, io, json
from runpy import run_path
from src.infrastructure.database.operator_store import OperatorDbRecord, OperatorTarget
import src.infrastructure.reporting.analytics as analytics
import src.web.reporter as reporting
from src.privacy import set_nik_masking
t=run_path("tests/contract/test_reporter_aggregation.py")
ROOT=Path("C:/TaskBotPhase1Virtual")
reporting.now_iso=lambda: t["END"]
analytics.datetime=t["FrozenDatetime"]
reporting.log_print=lambda *a,**kw: None
set_nik_masking(False)
def snapshot(total, skip):
    memory=MemoryFiles()
    mapped=[]
    with memory.active():
        for op in (1,2):
            label=f"operator_{op:02}"
            rep=t["make_reporter"](ROOT,label)
            target=OperatorTarget(f"OPERATOR_{op}",label,operator_id=label)
            for i in range(total//2):
                # Deliberately invalid region prefix, digits only; these never reach a shop.
                ident=f"000000{op}{i:09}"
                status="skipped_max_kuota" if skip and op==2 and i==total//2-1 else "completed"
                row=reporting.TransactionRow(nik=ident,status=status,operator_id=label,run_id="fixed_run",started_at=t["START"],finished_at=t["END"])
                rep._record_row(row)
                mapped.append(asdict(OperatorDbRecord.from_report_payload(asdict(row),target)))
            rep.write_files()
            with rep.csv_path.open(encoding="utf-8",newline="") as stream:
                csv_keys=[(r["nik"],r["status"]) for r in csv.DictReader(stream)]
            with rep.jsonl_path.open(encoding="utf-8") as stream:
                json_keys=[(r["nik"],r["status"]) for r in map(json.loads,stream)]
            assert csv_keys==json_keys and len(csv_keys)==total//2
            expected=Counter(completed=total//2)
            if skip and op==2:
                expected["completed"]-=1
                expected["skipped_max_kuota"]=1
            assert Counter(s for _,s in csv_keys)==expected
    files={p.relative_to(ROOT).as_posix():b.getvalue() for p,b in memory.files.items()}
    assert len(files)==14 and len(mapped)==total
    assert [r["kuota_delta"] for r in mapped]==[1]*(total-int(skip))+[0]*int(skip)
    return files,mapped
def fingerprint(files):
    manifest=[(p,len(b),hashlib.sha256(b).hexdigest()) for p,b in sorted(files.items())]
    return hashlib.sha256(json.dumps(manifest,separators=(",",":")).encode()).hexdigest()
for total,skip in [(30,True),(200,False)]:
    files,rows=snapshot(total,skip)
    files2,rows2=snapshot(total,skip)
    print("repeat file differences",sorted(k for k in files if files.get(k)!=files2.get(k)))
    assert files==files2 and rows==rows2
    row_hash=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str,separators=(",",":")).encode()).hexdigest()
    print("rows",total,"quota increments",sum(r["kuota_delta"] for r in rows),"files",len(files),"total bytes",sum(map(len,files.values())))
    print("file manifest sha256",fingerprint(files))
    print("DB payload list sha256",row_hash)

'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
repeat file differences []
rows 30 quota increments 29 files 14 total bytes 55400
file manifest sha256 3a98b08c5c5b8d00b52c6a029954f1c856fc3fc648b1864eddf2d876f9f7125e
DB payload list sha256 9c9178f8511b7ec09072ff0b0969a9a13fb601866f900689b995a9b4e5863d73
repeat file differences []
rows 200 quota increments 200 files 14 total bytes 269028
file manifest sha256 4bb7e78e669bc0db72c7882bd46f31b483aafec3f56c97f20b8f6d1bf522c6af
DB payload list sha256 395eccbb90006bbd867d2918adff045d8c81eb6d2935235703652c4360df2527
```

<a id="b36"></a>
**B36**

```powershell
foreach ($phaseRows in @(224, 1036)) {
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
from collections import Counter
from dataclasses import asdict
import csv, hashlib, io, json
from runpy import run_path
from src.infrastructure.database.operator_store import OperatorDbRecord, OperatorTarget
import src.infrastructure.reporting.analytics as analytics
import src.web.reporter as reporting
from src.privacy import set_nik_masking
t=run_path("tests/contract/test_reporter_aggregation.py")
ROOT=Path("C:/TaskBotPhase1Virtual")
reporting.now_iso=lambda: t["END"]
analytics.datetime=t["FrozenDatetime"]
reporting.log_print=lambda *a,**kw: None
set_nik_masking(False)
def snapshot(total, skip):
    memory=MemoryFiles()
    mapped=[]
    with memory.active():
        for op in (1,2):
            label=f"operator_{op:02}"
            rep=t["make_reporter"](ROOT,label)
            target=OperatorTarget(f"OPERATOR_{op}",label,operator_id=label)
            for i in range(total//2):
                # Deliberately invalid region prefix, digits only; these never reach a shop.
                ident=f"000000{op}{i:09}"
                status="skipped_max_kuota" if skip and op==2 and i==total//2-1 else "completed"
                row=reporting.TransactionRow(nik=ident,status=status,operator_id=label,run_id="fixed_run",started_at=t["START"],finished_at=t["END"])
                rep._record_row(row)
                mapped.append(asdict(OperatorDbRecord.from_report_payload(asdict(row),target)))
            rep.write_files()
            with rep.csv_path.open(encoding="utf-8",newline="") as stream:
                csv_keys=[(r["nik"],r["status"]) for r in csv.DictReader(stream)]
            with rep.jsonl_path.open(encoding="utf-8") as stream:
                json_keys=[(r["nik"],r["status"]) for r in map(json.loads,stream)]
            assert csv_keys==json_keys and len(csv_keys)==total//2
            expected=Counter(completed=total//2)
            if skip and op==2:
                expected["completed"]-=1
                expected["skipped_max_kuota"]=1
            assert Counter(s for _,s in csv_keys)==expected
    files={p.relative_to(ROOT).as_posix():b.getvalue() for p,b in memory.files.items()}
    assert len(files)==14 and len(mapped)==total
    assert [r["kuota_delta"] for r in mapped]==[1]*(total-int(skip))+[0]*int(skip)
    return files,mapped
def fingerprint(files):
    manifest=[(p,len(b),hashlib.sha256(b).hexdigest()) for p,b in sorted(files.items())]
    return hashlib.sha256(json.dumps(manifest,separators=(",",":")).encode()).hexdigest()
import ctypes as C, gc, statistics, time, threading
from ctypes import wintypes as W
class Counters(C.Structure):
    _fields_=[("cb",W.DWORD),("faults",W.DWORD)]+[(s,C.c_size_t) for s in ("peak_ws","ws","qpp","qp","qnp","qn","pf","ppf")]
kernel=C.WinDLL("kernel32",use_last_error=True)
kernel.GetCurrentProcess.restype=W.HANDLE
process=kernel.GetCurrentProcess()
psapi=C.WinDLL("psapi",use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes=[W.HANDLE,C.POINTER(Counters),W.DWORD]
def memory():
    c=Counters(); c.cb=C.sizeof(c)
    if not psapi.GetProcessMemoryInfo(process,C.byref(c),c.cb): raise C.WinError(C.get_last_error())
    return c.ws,c.peak_ws
size=int(sys.argv[1])
warm, rows=snapshot(size,True)
digest=fingerprint(warm); nbytes=sum(map(len,warm.values()))
del warm,rows
elapsed=[]; peaks=[]
for _ in range(5):
    gc.collect()
    done=threading.Event()
    samples=[memory()[0]]
    def sample():
        while not done.wait(0.01):
            samples.append(memory()[0])
    thread=threading.Thread(target=sample)
    thread.start()
    try:
        start=time.perf_counter_ns()
        files,rows=snapshot(size,True)
        elapsed.append(round((time.perf_counter_ns()-start)/1e6,2))
        samples.append(memory()[0])
    finally:
        done.set(); thread.join()
    peaks.append(round(max(samples)/1048576,2))
    assert fingerprint(files)==digest
    del files,rows
print("rows",size,"files",14,"output bytes",nbytes)
print("elapsed ms",elapsed,"median",statistics.median(elapsed))
print("sampled peak working set MiB",peaks,"median",statistics.median(peaks))
print("process lifetime peak MiB",round(memory()[1]/1048576,2))

'@ | .\.venv\Scripts\python.exe -I -B - $phaseRows
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

```text
rows 224 files 14 output bytes 299876
elapsed ms [211.89, 207.44, 208.88, 206.14, 205.8] median 207.44
sampled peak working set MiB [45.51, 45.56, 45.56, 45.57, 45.58] median 45.56
process lifetime peak MiB 45.9
rows 1036 files 14 output bytes 1323002
elapsed ms [2133.56, 2142.3, 2151.15, 2157.28, 2181.69] median 2151.15
sampled peak working set MiB [49.52, 49.59, 49.62, 49.89, 49.55] median 49.59
process lifetime peak MiB 49.89
```

<a id="b37"></a>
**B37**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class TempInMemory:
    @pytest.fixture
    def tmp_path(self):
        with MemoryFiles().active():
            yield ROOT
mods=[
    "tests/contract/test_database_setup_lifecycle.py",
    "tests/contract/test_monthly_quota_lifecycle.py",
    "tests/contract/test_db_sync_lifecycle.py",
    "tests/contract/test_reporter_aggregation.py",
    "tests/unit/test_database_report_payload_lifecycle.py",
    "tests/unit/test_operator_database.py",
    "tests/unit/test_database_report_syncer.py",
    "tests/unit/test_transaction_outcome.py",
    "tests/contract/test_transaction_processor.py::test_dashboard_zero_stock_records_one_terminal_row_before_stopping",
    "tests/contract/test_transaction_processor.py::test_unconfirmed_sale_never_completes_or_retries",
    "tests/contract/test_transaction_processor.py::test_successful_update_restarts_same_nik_without_consuming_retry_budgets",
    "tests/contract/test_transaction_processor.py::test_repeated_update_after_same_nik_restart_is_terminal_without_retry",
    "tests/unit/test_customer_workflow.py::test_requested_happy_customer_path_matrix",
]
raise SystemExit(pytest.main([*opts,*mods],plugins=[TempInMemory()]))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
E   AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
```

<a id="b38"></a>
**B38**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class TempInMemory:
    @pytest.fixture
    def tmp_path(self):
        with MemoryFiles().active():
            yield ROOT
mods=[
    "tests/contract/test_database_setup_lifecycle.py",
    "tests/contract/test_monthly_quota_lifecycle.py",
    "tests/contract/test_db_sync_lifecycle.py",
    "tests/contract/test_reporter_aggregation.py",
    "tests/unit/test_database_report_payload_lifecycle.py",
    "tests/unit/test_operator_database.py",
    "tests/unit/test_database_report_syncer.py",
    "tests/unit/test_transaction_outcome.py",
    "tests/contract/test_transaction_processor.py::test_dashboard_zero_stock_records_one_terminal_row_before_stopping",
    "tests/contract/test_transaction_processor.py::test_unconfirmed_sale_never_completes_or_retries",
    "tests/contract/test_transaction_processor.py::test_successful_update_restarts_same_nik_without_consuming_retry_budgets",
    "tests/contract/test_transaction_processor.py::test_repeated_update_after_same_nik_restart_is_terminal_without_retry",
    "tests/unit/test_customer_workflow.py::test_requested_happy_customer_path_matrix",
]
from collections import Counter
class Results:
    def __init__(self):
        self.passed=0
        self.fails=Counter()
        self.examples={}
    def pytest_runtest_logreport(self, report):
        if report.when=="call" and report.passed:
            self.passed+=1
        if report.failed:
            failure=getattr(report.longrepr, "reprcrash", None)
            msg=getattr(failure,"message","unknown failure").splitlines()[0]
            if len(msg)>190: msg=msg[:185]+"..."
            key=(report.when, msg)
            self.fails[key]+=1
            self.examples.setdefault(key,report.nodeid.split("[")[0])
report=Results()
rc=pytest.main(["-p","no:terminal","--noconftest","-p","no:cacheprovider","-p","no:logging",*mods],plugins=[TempInMemory(),report])
print("passed",report.passed,"test failures",sum(v for (phase,_),v in report.fails.items() if phase=="call"),"fixture errors",sum(v for (phase,_),v in report.fails.items() if phase!="call"))
for key,n in sorted(report.fails.items()): print(n,*key, "|",report.examples[key])
raise SystemExit(rc)
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
FileNotFoundError: [Errno 2] No usable temporary directory found in ['C:\\Users\\user\\AppData\\Local\\Temp', 'C:\\Users\\user\\AppData\\Local\\Temp', 'C:\\Users\\user\\AppData\\Local\\Temp', 'C:\\windows\\Temp', 'c:\\temp', 'c:\\tmp', '\\temp', '\\tmp', 'D:\\MyProject\\TaskBot']
```

<a id="b39"></a>
**B39**

```powershell
rg -n 'taskbot_main\.(OperatorDatabaseManager|OperatorTargets|OperatorDatabase|DatabaseConfig|DatabaseReportSyncer|_DatabaseReportSyncer)|setattr\(taskbot_main|from src.infrastructure.database|from src.application' tests/unit/test_database_report_syncer.py tests/contract/test_db_sync_lifecycle.py main.py | Select-Object -First 39
```

```text
tests/contract/test_db_sync_lifecycle.py:14:from src.infrastructure.database import report_syncer
tests/contract/test_db_sync_lifecycle.py:106:    monkeypatch.setattr(taskbot_main.OperatorDatabaseManager, "from_env", from_env)
main.py:19:from src.infrastructure.database.report_syncer import (
```

<a id="b40"></a>
**B40**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class TempInMemory:
    @pytest.fixture
    def tmp_path(self):
        with MemoryFiles().active():
            yield ROOT
mods=[
    "tests/contract/test_database_setup_lifecycle.py",
    "tests/contract/test_monthly_quota_lifecycle.py",
    "tests/contract/test_db_sync_lifecycle.py",
    "tests/contract/test_reporter_aggregation.py",
    "tests/unit/test_database_report_payload_lifecycle.py",
    "tests/unit/test_operator_database.py",
    "tests/unit/test_database_report_syncer.py",
    "tests/unit/test_transaction_outcome.py",
    "tests/contract/test_transaction_processor.py::test_dashboard_zero_stock_records_one_terminal_row_before_stopping",
    "tests/contract/test_transaction_processor.py::test_unconfirmed_sale_never_completes_or_retries",
    "tests/contract/test_transaction_processor.py::test_successful_update_restarts_same_nik_without_consuming_retry_budgets",
    "tests/contract/test_transaction_processor.py::test_repeated_update_after_same_nik_restart_is_terminal_without_retry",
    "tests/unit/test_customer_workflow.py::test_requested_happy_customer_path_matrix",
]
from collections import Counter
class Results:
    def __init__(self):
        self.passed=0
        self.fails=Counter()
        self.examples={}
    def pytest_runtest_logreport(self, report):
        if report.when=="call" and report.passed:
            self.passed+=1
        if report.failed:
            failure=getattr(report.longrepr, "reprcrash", None)
            msg=getattr(failure,"message","unknown failure").splitlines()[0]
            if len(msg)>190: msg=msg[:185]+"..."
            key=(report.when, msg)
            self.fails[key]+=1
            self.examples.setdefault(key,report.nodeid.split("[")[0])
report=Results()
rc=pytest.main(["-s","-p","no:terminal","--noconftest","-p","no:cacheprovider","-p","no:logging",*mods],plugins=[TempInMemory(),report])
print("passed",report.passed,"test failures",sum(v for (phase,_),v in report.fails.items() if phase=="call"),"fixture errors",sum(v for (phase,_),v in report.fails.items() if phase!="call"))
for key,n in sorted(report.fails.items()): print(n,*key, "|",report.examples[key])
raise SystemExit(rc)
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
passed 233 test failures 7 fixture errors 43
7 call PermissionError: subprocess.Popen | tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization
43 setup AttributeError: module 'main' has no attribute 'OperatorDatabaseManager' | tests/contract/test_db_sync_lifecycle.py::test_one_off_success_lifecycle
```

<a id="b41"></a>
**B41**

```powershell
@'
from pathlib import Path
for f,a,b in [("tests/unit/test_database_report_syncer.py",205,255),("main.py",9,35),("src/infrastructure/database/report_syncer.py",1,75),("tests/unit/test_database_report_syncer.py",35,85)]:
    s=Path(f).read_text(encoding="utf-8-sig").splitlines()
    print(f)
    for i in range(a,min(b,len(s))+1): print(f"{i}: {s[i-1]}")
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
231:         with patch.object(psycopg2, "connect") as connect, \
238:             assert main.DatabaseReportSyncer is report_syncer.DatabaseReportSyncer
239:             assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
240:             assert main._DATABASE_SETUP_LOCK is report_syncer._DATABASE_SETUP_LOCK
```

<a id="b42"></a>
**B42**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
import subprocess
original_run = subprocess.run
def isolated_child(argv,*args,**kwargs):
    if not (isinstance(argv,list) and len(argv)==3 and argv[:2]==[sys.executable,"-c"]
            and "main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager" in argv[2]):
        raise PermissionError("unexpected child")
    return original_run([sys.executable,"-I","-B","-c","import os, sys\nfrom pathlib import Path\nos.environ.update(PYTHON_DOTENV_DISABLED=\"1\", PYTEST_DISABLE_PLUGIN_AUTOLOAD=\"1\", LOGURU_AUTOINIT=\"0\")\ndef audit(event, args):\n    if event == \"open\":\n        name, _, flags = args\n        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == \".env\":\n            raise PermissionError(\"private environment file\")\n        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):\n            raise PermissionError(\"physical file write\")\n    if event in {\"subprocess.Popen\",\"os.system\",\"socket.connect\",\"socket.bind\",\"socket.getaddrinfo\",\"os.mkdir\",\"os.rename\",\"os.remove\",\"os.rmdir\"}:\n        raise PermissionError(event)\nsys.addaudithook(audit)\nsys.path.insert(0, str(Path.cwd()))\n"+argv[2]],*args,**kwargs)
subprocess.run=isolated_child
from contextlib import ExitStack, contextmanager, nullcontext
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path.cwd() / "__phase1_virtual__"
class MemoryFiles:
    def __init__(self):
        self.files = {}
        self.dirs = {ROOT}
    def exists(self, path):
        return path in self.files or path in self.dirs
    def stat(self, path, **kwargs):
        if path in self.files:
            return SimpleNamespace(st_size=self.files[path].getbuffer().nbytes, st_mode=0o100600)
        if path in self.dirs:
            return SimpleNamespace(st_size=0, st_mode=0o40700)
        raise FileNotFoundError(path)
    def mkdir(self, path, *args, **kwargs):
        self.dirs.add(path)
        self.dirs.update(p for p in path.parents if p == ROOT or ROOT in p.parents)
    def touch(self, path, *args, **kwargs):
        self.files.setdefault(path, BytesIO())
    @contextmanager
    def open(self, path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "r" in mode and path not in self.files:
            raise FileNotFoundError(path)
        if path not in self.files:
            self.files[path] = BytesIO()
        buf = self.files[path]
        buf.seek(0, 2 if "a" in mode else 0)
        if "w" in mode:
            buf.truncate()
        if "b" in mode:
            yield buf
        else:
            handle=TextIOWrapper(buf, encoding=encoding or "utf-8", errors=errors, newline=newline)
            try:
                yield handle
            finally:
                handle.flush()
                handle.detach()
    @contextmanager
    def active(self):
        def routed(original, local):
            def call(path, *args, **kwargs):
                if path == ROOT or ROOT in path.parents:
                    return local(path,*args,**kwargs)
                return original(path,*args,**kwargs)
            return call
        with ExitStack() as stack:
            for name in ("exists","stat","mkdir","touch","open"):
                stack.enter_context(patch.object(Path,name,routed(getattr(Path,name),getattr(self,name))))
            yield self
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
class TempInMemory:
    @pytest.fixture
    def tmp_path(self):
        with MemoryFiles().active():
            yield ROOT
mods=[
    "tests/contract/test_database_setup_lifecycle.py",
    "tests/contract/test_monthly_quota_lifecycle.py",
    "tests/contract/test_db_sync_lifecycle.py",
    "tests/contract/test_reporter_aggregation.py",
    "tests/unit/test_database_report_payload_lifecycle.py",
    "tests/unit/test_operator_database.py",
    "tests/unit/test_database_report_syncer.py",
    "tests/unit/test_transaction_outcome.py",
    "tests/contract/test_transaction_processor.py::test_dashboard_zero_stock_records_one_terminal_row_before_stopping",
    "tests/contract/test_transaction_processor.py::test_unconfirmed_sale_never_completes_or_retries",
    "tests/contract/test_transaction_processor.py::test_successful_update_restarts_same_nik_without_consuming_retry_budgets",
    "tests/contract/test_transaction_processor.py::test_repeated_update_after_same_nik_restart_is_terminal_without_retry",
    "tests/unit/test_customer_workflow.py::test_requested_happy_customer_path_matrix",
]
from collections import Counter
class Results:
    def __init__(self):
        self.passed=0
        self.fails=Counter()
        self.examples={}
    def pytest_runtest_logreport(self, report):
        if report.when=="call" and report.passed:
            self.passed+=1
        if report.failed:
            failure=getattr(report.longrepr, "reprcrash", None)
            msg=getattr(failure,"message","unknown failure").splitlines()[0]
            if len(msg)>190: msg=msg[:185]+"..."
            if "Traceback (most recent call last)" in msg and "module 'main' has no attribute 'OperatorDatabaseManager'" in str(report.longrepr):
                msg="child assertion: module main has no attribute OperatorDatabaseManager"
            key=(report.when, msg)
            self.fails[key]+=1
            self.examples.setdefault(key,report.nodeid.split("[")[0])
report=Results()
rc=pytest.main(["-s","-p","no:terminal","--noconftest","-p","no:cacheprovider","-p","no:logging",*mods],plugins=[TempInMemory(),report])
print("passed",report.passed,"test failures",sum(v for (phase,_),v in report.fails.items() if phase=="call"),"fixture errors",sum(v for (phase,_),v in report.fails.items() if phase!="call"))
for key,n in sorted(report.fails.items()): print(n,*key, "|",report.examples[key])
raise SystemExit(rc)
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
passed 233 test failures 7 fixture errors 43
7 call AssertionError | tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization
43 setup AttributeError: module 'main' has no attribute 'OperatorDatabaseManager' | tests/contract/test_db_sync_lifecycle.py::test_one_off_success_lifecycle
```

<a id="b43"></a>
**B43**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"subprocess.Popen","os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
from src.infrastructure.database.operator_store import OperatorDatabaseManager
print("syncer preloaded", "src.infrastructure.database.report_syncer" in sys.modules)
from src.infrastructure.database import report_syncer
import main
for name in ("DatabaseReportSyncer", "OperatorDatabaseManager", "_DATABASE_SETUP_LOCK", "_database_report_payload"):
    print(name, "main",hasattr(main,name),"syncer module",hasattr(report_syncer,name))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
syncer preloaded False
DatabaseReportSyncer main True syncer module True
OperatorDatabaseManager main False syncer module True
_DATABASE_SETUP_LOCK main False syncer module True
_database_report_payload main False syncer module True
```

<a id="b44"></a>
**B44**

```powershell
@'
import os, sys
from pathlib import Path
os.environ.update(PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", LOGURU_AUTOINIT="0")
def audit(event, args):
    if event == "open":
        name, _, flags = args
        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == ".env":
            raise PermissionError("private environment file")
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("physical file write")
    if event in {"os.system","socket.connect","socket.bind","socket.getaddrinfo","os.mkdir","os.rename","os.remove","os.rmdir"}:
        raise PermissionError(event)
sys.addaudithook(audit)
sys.path.insert(0, str(Path.cwd()))
import psycopg2
def no_db(*args, **kwargs):
    raise AssertionError("real DB connection attempted")
psycopg2.connect = no_db
import subprocess
original_run = subprocess.run
def isolated_child(argv,*args,**kwargs):
    if not (isinstance(argv,list) and len(argv)==3 and argv[:2]==[sys.executable,"-c"]
            and "main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager" in argv[2]):
        raise PermissionError("unexpected child")
    result=original_run([sys.executable,"-I","-B","-c","import os, sys\nfrom pathlib import Path\nos.environ.update(PYTHON_DOTENV_DISABLED=\"1\", PYTEST_DISABLE_PLUGIN_AUTOLOAD=\"1\", LOGURU_AUTOINIT=\"0\")\ndef audit(event, args):\n    if event == \"open\":\n        name, _, flags = args\n        if isinstance(name, (bytes, str)) and Path(os.fsdecode(name)).name.lower() == \".env\":\n            raise PermissionError(\"private environment file\")\n        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):\n            raise PermissionError(\"physical file write\")\n    if event in {\"subprocess.Popen\",\"os.system\",\"socket.connect\",\"socket.bind\",\"socket.getaddrinfo\",\"os.mkdir\",\"os.rename\",\"os.remove\",\"os.rmdir\"}:\n        raise PermissionError(event)\nsys.addaudithook(audit)\nsys.path.insert(0, str(Path.cwd()))\n"+argv[2]],*args,**kwargs)
    if result.returncode: print('child stderr last line:', result.stderr.strip().splitlines()[-1])
    return result
subprocess.run=isolated_child
import pytest
opts=["-q","-s","--noconftest","-p","no:cacheprovider","-p","no:logging","--tb=line"]
case="tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization"
raise SystemExit(pytest.main([*opts,case,"--maxfail=1"]))
'@ | .\.venv\Scripts\python.exe -I -B -
```

```text
child stderr last line: AttributeError: module 'main' has no attribute 'OperatorDatabaseManager'
FAILED tests/unit/test_database_report_syncer.py::test_fresh_import_identity_and_no_database_initialization[import src.infrastructure.database.report_syncer]
1 failed in 0.96s
```

<a id="b45"></a>
**B45**

```powershell
rg -n 'from .*report_syncer|DatabaseReportSyncer|OperatorDatabaseManager|_DATABASE_SETUP_LOCK' main.py src/infrastructure/database/report_syncer.py | Select-Object -First 22
```

```text
main.py:19:from src.infrastructure.database.report_syncer import (
main.py:20:    DatabaseReportSyncer,
src/infrastructure/database/report_syncer.py:9:from src.infrastructure.database.operator_store import OperatorDatabaseManager
src/infrastructure/database/report_syncer.py:14:_DATABASE_SETUP_LOCK = Lock()
```

<a id="b46"></a>
**B46**

```powershell
@'
from pathlib import Path
import csv, json
for m in sorted(Path("reports").glob("*/*/*/20261123_*/run_meta.json")):
    for i,p in enumerate(sorted(m.parent.glob("operators/*/items.jsonl")),1):
        with p.with_name("items.csv").open(encoding="utf-8-sig",newline="") as stream:
            reader=csv.DictReader(stream); header=reader.fieldnames; a=list(reader)
        with p.open(encoding="utf-8-sig") as stream: b=[json.loads(s) for s in stream if s.strip()]
        assert len(a)==len(b) and all(set(row)==set(header) for row in b)
        different=sum(row[k]!=("" if obj[k] is None else str(obj[k])) for row,obj in zip(a,b,strict=True) for k in header)
        print("operator",i,"rows",len(a),"fields",len(header),"field differences",different)
        assert different==0
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
operator 1 rows 15 fields 18 field differences 0
operator 2 rows 15 fields 18 field differences 0
```

<a id="b47"></a>
**B47**

```powershell
@'
from pathlib import Path
import re
for m in sorted(Path("reports").glob("*/*/*/*/run_meta.json")):
    if re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}",m.parent.name):
        print(m.as_posix())
        if m.parent.name.startswith("20261123_"):
            for n in ("items.csv","items.jsonl","summary.json"):
                for p in sorted(m.parent.glob("operators/*/"+n)): print(p.as_posix())
'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
reports/2026/11/23/20261123_062628_be17/run_meta.json
reports/2026/11/23/20261123_062628_be17/operators/operator_01/items.csv
reports/2026/11/23/20261123_062628_be17/operators/operator_02/items.csv
```

<a id="b48"></a>
**B48**

```powershell
@'
from pathlib import Path
import re
p=Path("docs/2026-11-23-phase-1-behavior-baseline.md")
doc=p.read_text(encoding="utf-8")
body=doc.split("\n## Command evidence\n")[0]
findings=re.findall(r"\*\*(F\d+) [^*]*?—",body)
assert findings==[f"F{i}" for i in range(48,56)],findings
for need in ("29** | **1", "233 passed, 7 failed, 43 setup errors","207.44 ms","45.56 MiB","2,151.15 ms","49.59 MiB","108 of 160","55,400 bytes","269,028 bytes"):
    assert need in body, need
for target in re.findall(r"\]\(([^)]+)\)",body):
    path=target.split("#",1)[0]
    assert not path or (p.parent/path).exists(),target
assert not re.search(r"(?<![A-Za-z0-9])\d{16}(?![A-Za-z0-9])",doc)
print("8 findings, outcomes, benchmark, reference sizes, file links and identifier check passed")

'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
re.PatternError: multiple repeat at position 17
```

<a id="b49"></a>
**B49**

```powershell
git diff --stat
```

```text
 .gitignore | 6 +++++-
 1 file changed, 5 insertions(+), 1 deletion(-)
```

<a id="b50"></a>
**B50**

```powershell
git status --short --branch --untracked-files=all
```

```text
## modernize
 M .gitignore
?? docs/2026-11-23-phase-1-behavior-baseline.md
?? docs/MODERNIZATION_PLAN.md
```

<a id="b51"></a>
**B51**

```powershell
@'
from pathlib import Path
import re
p=Path("docs/2026-11-23-phase-1-behavior-baseline.md")
doc=p.read_text(encoding="utf-8")
body=doc.split("\n## Command evidence\n")[0]
findings=re.findall(r"\*\*(F\d+) ",body)
assert findings==[f"F{i}" for i in range(48,56)],findings
for need in ("29** | **1", "233 passed, 7 failed, 43 setup errors","207.44 ms","45.56 MiB","2,151.15 ms","49.59 MiB","108 of 160","55,400 bytes","269,028 bytes"):
    assert need in body, need
for target in re.findall(r"\]\(([^)]+)\)",body):
    path=target.split("#",1)[0]
    assert not path or (p.parent/path).exists(),target
assert not re.search(r"(?<![A-Za-z0-9])\d{16}(?![A-Za-z0-9])",doc)
print("8 findings, outcomes, benchmark, reference sizes, file links and identifier check passed")

'@ | .\.venv\Scripts\python.exe -I -B -S -
```

```text
8 findings, outcomes, benchmark, reference sizes, file links and identifier check passed
```

B12 returned exit code 1 for no matches in the three named files. B37 first exposed the missing module name. B38 stopped before collection because pytest tried to create a temporary capture file. B40 disabled capture, but its read-only guard also prevented seven fresh-process tests from starting. B42 permitted only their inspected Python child and kept file and database protection in that child. B44 isolated the failed assertion. B48 encountered a non-ASCII Windows pipe encoding issue in the document checker. The ASCII pattern in B51 passed. B49 reports the pre-existing tracked `.gitignore` diff. B50 also shows the previous untracked modernization plan and this new phase document.

</details>

<details>
<summary>Code graph lookups and direct-source coverage</summary>

```text
search_graph({"project":"D-MyProject-TaskBot","file_pattern":"*file_writer.py","name_pattern":"^(append.*|write.*|File.*)$","limit":24})
  append_row Method 57-60 1 2
```

```text
trace_path({"project":"D-MyProject-TaskBot","function_name":"D-MyProject-TaskBot.src.infrastructure.reporting.file_writer.FileWriter.append_row","direction":"inbound","depth":1,"limit":8})
  _record_row 1
```

```text
get_code_snippet({"project":"D-MyProject-TaskBot","qualified_name":"D-MyProject-TaskBot.src.infrastructure.reporting.file_writer.FileWriter.append_row"})
"start_line":57,"end_line":60
```

`check_index_coverage` was run for project `D-MyProject-TaskBot`. The exact path sequence is the source list below, followed by every output path from B47, in order. It was split into groups of 20 (the last group contains six). The first call also used `scopes=["tests","reports"]` and `scope_limit=5`.

```text
AGENTS.md
docs/MODERNIZATION_PLAN.md
main.py
src/application/services/account_runner.py
src/orchestration/transaction_processor.py
src/web/reporter.py
src/infrastructure/reporting/file_writer.py
src/infrastructure/reporting/models.py
src/infrastructure/database/operator_store.py
src/infrastructure/database/report_syncer.py
tests/unit/test_database_report_syncer.py
tests/contract/test_db_sync_lifecycle.py
tests/contract/test_reporter_aggregation.py
tests/contract/reporter_aggregation_legacy.json
tests/contract/test_database_setup_lifecycle.py
tests/contract/test_monthly_quota_lifecycle.py
tests/unit/test_operator_database.py
tests/contract/test_transaction_processor.py
```

The graph returned `excluded/not_tracked` for 169 paths and `no_recorded_issue/metadata_changed` for 17. B09, B13, B18, B32 and B46 read the archive from disk. The conclusions about code use direct source reads and executed tests.

</details>

