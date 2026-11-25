# Database plan · Who goes next?

- **Goal.** Let the database choose tomorrow’s customer list instead of a hand-made list, without changing what a run does with the list it gets.
- **Already confirmed by the owner.** The first Operator 1 Lowokwaru query is the reference. Customers blocked by monthly quota get another chance next month. Customers blocked by stock get another chance the next day. The daily target is 100 stock units per operator, as reported by the owner.
- **Proposed order.** Agree on examples on paper → preview a list on today’s tables → design simpler tables → rehearse copying and restoring them → measure indexes → maybe switch the app’s input. Each step has its own approval and proof below.
- **Status.** Brainstorming only. No database or code change. DB1 starts once Q1–Q4 are answered. DB6 would change daily operation and needs your explicit go-ahead.
- **Related.** [Project structure plan](2026-11-25-plan-project-structure.md) (the database code moves in its Phase R4) · [Modernization plan](2026-11-23-plan-modernization.md)

## Waiting on the owner

### Not finished

- DB1–DB6 are proposals. None has started.
- The saved query gives some customers priority. It does not remember where yesterday’s operator stopped ([F120](#f120--verified--eligibility-comes-before-priority)).
- Two area headings disagree with their filters ([F121](#f121--verified--two-area-labels-disagree-with-their-filters)).
- The repeatable example runs on one machine only ([F140](#f140--partial--the-dummy-example-can-be-repeated-on-one-machine-only)).

### Questions

- [Q1 · Who goes first tomorrow?](#questions-and-answers) (partly answered)
- [Q2 · Which area and operator?](#questions-and-answers)
- [Q3 · Who can come back?](#questions-and-answers)
- [Q4 · Where are the quota and date boundaries?](#questions-and-answers)
- [Q5 · When do we stop and resume?](#questions-and-answers)
- [Q6 · What belongs to a customer and what belongs to the operator?](#questions-and-answers)
- [Q7 · How much history is needed?](#questions-and-answers)
- [Q8 · What would justify an index?](#questions-and-answers)
- [Q9 · Which clock decides “today”?](#questions-and-answers)
- [Q10 · Which database account may the preview use?](#questions-and-answers)
- [Q11 · How are schema changes written and undone?](#questions-and-answers)
- [Q12 · Where does the repeatable dummy example live?](#questions-and-answers)
- [Q13 · Who may see the preview list?](#questions-and-answers)

### Confirmations

- Confirm that the app keeps reading the configured customer list until DB6 is approved.
- Confirm that every schema change is first rehearsed on the local test instance, with a backup and a restore, before any real database is touched.
- Confirm that “100 stock units per operator” is a daily stop target, not a limit on how many rows the preview returns (Q5, Q8).

## Questions and answers

Each question has a suggested answer. Replace `*open*` with your answer, or write “agree” to take the suggestion. Q1–Q8 were called DB-Q1–DB-Q8 before. Their numbers did not change.

- **Q1 · Who goes first tomorrow?** Customer 3 hits no stock. Customer 4 was next but never reached. A new customer joins overnight. Should 3 go first, then 4, then the new customer? What if someone else was blocked by monthly quota last month? **Owner answer so far:** customer 3 gets another chance the next day. **Still open:** the order of the untouched tail, new arrivals and old monthly cases. The reference query puts an eligible old monthly case first. **Suggested answer:** write down the exact expected list for both examples in DB1. **Owner answer:** *open* for the rest
- **Q2 · Which area and operator?** Is each run inside Lowokwaru only, outside only, or inside first and outside once the inside list runs out? Is it the same rule for operator 2? Does the six-digit prefix define membership even if a customer moves? **Suggested answer:** an explicit choice per operator. The notebook headings disagree with two filters (F121). **Owner answer:** *open*
- **Q3 · Who can come back?** May a completed customer reappear the next day or the same day? Should today’s no-stock or this month’s max-quota rows stay at the bottom, or disappear until they are eligible? Keep all five blocked descriptions excluded? **Suggested answer:** show waiting and excluded reasons separately in the preview, so you can see which list you would actually use. **Owner answer:** *open*
- **Q4 · Where are the quota and date boundaries?** Include quota exactly 5? What about 6 from last month, before the monthly reset? Use the last status update or a recorded attempt time? **Suggested answer:** agree on before-reset, after-reset, midnight and month-end examples. The saved query includes 5 and reads the row’s update date. The app also has a separate monthly reset (F120, F122). The clock question is now Q9. **Owner answer:** *open*
- **Q5 · When do we stop and resume?** Stop on the first no-stock result, after 100 confirmed units, or whichever comes first? If the app restarts, should the same customer be first? How should ties, newly added customers, repeat inputs or two operators at once be handled? **Suggested answer:** keep today’s stop-on-stock behavior during the comparison. Add a daily list with saved positions only if yesterday’s exact order matters. **Owner answer:** *open*
- **Q6 · What belongs to a customer and what belongs to the operator?** Can two operators share the same person but have different quota, name, type or status? Can an identifier begin with zero? Which value wins when two records disagree? Who can correct it? **Suggested answer:** keep both source rows exactly as they are until these rules are agreed. Keep identifiers out of documents and logs used for the review. **Owner answer:** *open*
- **Q7 · How much history is needed?** The latest state and the last two sale times, every attempt, or a daily queue with unfinished positions? Who may view it and how long should it stay? Are old schemas, pgAdmin queries, spreadsheets or exports used elsewhere? **Suggested answer:** keep existing readers working and add history only for a named need. A delivery receipt answers whether a write was applied. It is a different record from a customer visit. **Owner answer:** *open*
- **Q8 · What would justify an index?** What row counts, operator mix, typical region size, peak memory and acceptable preview time should we test? Who approves switching inputs and who can switch back? **Suggested answer:** dummy distributions and a repeatable timed comparison first. The owner’s 100-unit target describes available stock, not table size or a query limit. **Owner answer:** *open*
- **Q9 · Which clock decides “today”?** The app writes `UPDATED_TIME` in the operator machine’s local time, without a time zone. The saved query compares it with PostgreSQL’s `CURRENT_DATE`, which follows the database session’s time zone ([F141](#f141--partial--the-app-and-the-saved-query-may-use-different-clocks)). If the two differ, “yesterday” and “last month” move. Options: (a) both use Asia/Jakarta explicitly, (b) both use the operator machine’s time zone, (c) leave it as it is and check that they match. **Suggested answer:** (c) now, by recording both settings in DB1. Choose (a) for the new design in DB3, because it does not depend on a machine setting. **Owner answer:** *open*
- **Q10 · Which database account may the preview use?** **Suggested answer:** a separate account that can only read the operator tables (`SELECT` only), with the preview running inside a read-only transaction. The app’s writing account is not used for previews. Creating a role is a database change, so it is rehearsed on the test instance first. **Owner answer:** *open*
- **Q11 · How are schema changes written and undone?** Options: (a) numbered plain SQL files in the repo, each with a matching undo file, run by hand in pgAdmin or `psql`, (b) a migration tool such as Alembic, which is a new dependency. **Suggested answer:** (a). It needs no new dependency and is easy to read. Every file is rehearsed on the test instance: backup → apply → check → undo → check. **Owner answer:** *open*
- **Q12 · Where does the repeatable dummy example live?** Today it is a private script on one machine ([F140](#f140--partial--the-dummy-example-can-be-repeated-on-one-machine-only)). **Suggested answer:** in DB1, add the dummy rows as a SQL file and a pytest test that uses the existing test-database settings. They hold dummy labels only, never real query results, so the next developer can repeat the example. **Owner answer:** *open*
- **Q13 · Who may see the preview list?** The preview shows identifiers and names of real customers. **Suggested answer:** only the operator, on their own machine. The preview is never written to a report file, a log, the repo or the future API. Documents show counts and dummy labels only. **Owner answer:** *open*

## F120 · VERIFIED · Eligibility comes before priority

The first query reads only `public."OPERATOR_1"`. A row must match the Lowokwaru prefix, avoid the five excluded descriptions and pass `"KUOTA" <= 5`. An otherwise first-priority row at 6 is absent. The exclusions cover invalid registered ID, unregistered consumer, under 17, cannot transact at this base and data needs update. The result includes nine named columns and then `*`. An application preview should explicitly define its fields before anyone relies on that result shape. [Saved SELECT, filters and returned fields](<../db_query/basic query.sql#L4>)

| Priority | Which eligible row comes next? |
| --- | --- |
| 0 | “Max kuota reached” with `UPDATED_TIME` before the first day of the current month. |
| 1 | “Sellable stock unavailable” with an update date earlier than today. |
| 2 | Any other eligible description, including a completed customer if it passes the filters. |
| 3 | The two waiting descriptions whose dates did not qualify above. These rows are still returned. |

Within a priority, lower `MAX_KUOTA` comes first, nulls last, then older `UPDATED_TIME`. There is no final unique sort key or row limit. If both keys tie, either order satisfies the query. A stable customer key could settle ties in a future recipe. Keeping yesterday’s positions would require information about yesterday’s list. [CASE and final sort keys](<../db_query/basic query.sql#L28>) · [PostgreSQL 18 ordering](https://www.postgresql.org/docs/18/queries-order.html)

**The owner’s drawing, checked with dummy rows.** Customers 1 and 2 finished yesterday, 3 ran out of stock, and 4–6 have other eligible statuses. We gave 4, 5 and 6 increasing maximum quotas. We added an old monthly case at quota 5, another at 6, one outside-area row, one blocked row and one waiting today. On PostgreSQL 18, the saved query returned the following labels in this order:

```text
old_month_at_5, customer_3, customer_4, customer_5, customer_6, customer_1, customer_2, wait_today
```

Customer 3 moved ahead of 4. Customer 4 beat 5 because of the fixture’s maximum quotas. The query never received yesterday’s list position. Customers 1 and 2 came back into the results. **UNVERIFIED** whether this is the order the owner wants with different quotas or newly arrived customers. The example uses a read-only transaction and synthetic rows.

## F121 · VERIFIED · Two area labels disagree with their filters

One “BUKAN LOWOKWARU” heading uses `= '357305'`. Another “LOWOKWARU” heading uses `<> '357305'`. Before copying a recipe, record its operator, actual filter and purpose. For the other SQL blocks, preserve the distinction between a next-customer list, a combined list, and an inspection or count. The existing catalogue gives locations without reproducing customer records. [First mismatch](<../db_query/basic query.sql#L108>) · [Second mismatch](<../db_query/basic query.sql#L274>) · [SQL catalogue](2026-11-23-plan-modernization.md#sql-catalogue)

## F122 · VERIFIED for the supplied schema and writer · Quota is stored per operator and customer

The export declares two tables with the same 14 columns. Each has its own `PRIMARY KEY ("NIK")`. It stores `NIK` as bigint, non-null current and maximum quota, update time without a time zone and two nullable sale times. The writer selects a table with `f"OPERATOR_{suffix}"`, has rules for newer, older and month-changing updates, and can reset old-month nonzero quota to 0 without replacing the update timestamp in that statement. The app reads `NIK_{suffix}` into an ordered list and stops that operator’s loop on the stock exception. **UNVERIFIED** whether the live schema matches this export or all configured customers already have DB rows. [Exported columns](<../db_query/schema backup.sql#L33>) · [Keys](<../db_query/schema backup.sql#L83>) · [Table selection](../../src/infrastructure/database/operator_store.py#L183) · [Quota rules](../../src/infrastructure/database/_operator_sql.py#L93) · [Monthly reset](../../src/infrastructure/database/operator_store.py#L484) · [Input](../../src/infrastructure/config/settings.py#L119) · [Operator loop](../../src/orchestration/transaction_processor.py#L95)

## F140 · PARTIAL · The dummy example can be repeated on one machine only

The ordered example in F120 comes from a private launcher outside the repo (`%LOCALAPPDATA%\TaskBot\phase1-pg18\verification\plans-20261125-db5e95a\`). The launcher is safe. Before it runs the query, it checks the cluster name, data directory, port and major version, and the Python part asserts a read-only session:

```text
fixture.ps1:13  select current_setting('cluster_name'), current_setting('data_directory'), inet_server_port(), current_setting('server_version_num')::int / 10000
fixture.py:13   assert cur.fetchone() == ("taskbot_phase1", "on")
```

But it hard-codes this checkout’s drive path and the PostgreSQL install path, and it reads a password protected by Windows (DPAPI) for the current user. Another developer cannot run it. **PARTIAL:** the safety checks are verified; whether the result repeats on another machine is **UNVERIFIED** (question Q12). The old [How to check](#how-to-check) command also wraps `powershell` in `uv run --locked`, which is not needed for a PowerShell script.

## F141 · PARTIAL · The app and the saved query may use different clocks

The app stores times as the machine’s local wall time, with the time zone removed:

```python
# src/infrastructure/database/operator_store.py:L1269-L1272
def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)
```

The saved query decides “earlier than today” and “before this month” with PostgreSQL’s `CURRENT_DATE`:

```sql
-- db_query/basic query.sql:L32 and L37
AND "UPDATED_TIME" < DATE_TRUNC('month', CURRENT_DATE::timestamp)
AND "UPDATED_TIME"::date < CURRENT_DATE
```

`CURRENT_DATE` follows the session’s `TimeZone` setting. **VERIFIED** for the code above. **UNVERIFIED** whether the operator machine and the database session use the same time zone. Check it with `SHOW TimeZone;` in pgAdmin and `Get-TimeZone` in PowerShell on the operator machine (question Q9). [Time normalization](../../src/infrastructure/database/operator_store.py#L1269) · [Saved query dates](<../db_query/basic query.sql#L32>)

## Review of this plan: what to improve

The earlier revision was a good start. The questions, dummy example and phases were clear. This review adds what was missing:

| Gap in the earlier revision | Change in this revision |
| --- | --- |
| No risk table. | [Risks](#risks) added. |
| No backup and restore step before the first schema change. | DB3 now starts with a backup and a timed restore of the test instance. |
| The preview could use the app’s writing account. | Q10 asks for a read-only account. DB2 uses a read-only transaction. |
| Customer identifiers could appear in a preview that is saved or shared. | Q13 limits who sees the preview and where it may be stored. |
| “Today” could mean two different clocks. | F141 and Q9. DB1 records both time zones. |
| No rule for how schema changes are written, numbered and undone. | Q11. Each change is a numbered SQL file with an undo file. |
| The dummy example could not be repeated by the next developer. | F140 and Q12. DB1 adds it to the repo as dummy data. |
| Two operators writing at the same time was only mentioned in passing. | DB4 now tests two operators writing at once. |
| The database plan and the restructuring plan could move the same code at once. | Shown in [Phases](#phases-proof-and-rollback): DB4–DB6 wait until structure Phase R4 is done, or happen before it starts, never in the same branch. |
| Question IDs (`DB-Q1`) and phase IDs carried no meaning on their own. | Every ID is shown next to its full title. |

## Proposed table design

Start with a read-only query over today’s tables. It is the cheapest way to check DB-Q1–Q5 and can be discarded independently. A second option is one shared state table keyed by operator and customer. It avoids one table definition per operator. A third option separates shared identity, operator state and optional visit history. Choose that design only after DB-Q6–Q7 establish which facts really are shared (F122).

| Proposed record | Key and meaning | What to prove before adopting it |
| --- | --- | --- |
| Operator | One stable operator ID. Keep a mapping to the existing suffix and display name. | Renaming a display name cannot merge accounts. |
| Customer | One internal customer ID and a unique external number *if* the owner confirms that identity rule. | Review conflicts using aggregate counts. A bigint export cannot tell us whether a leading zero was lost before import. Define the input format before converting it. |
| Operator customer state | One row per `(operator_id, customer_id)`. Keep quota, peak quota, status, problem/conflict, timestamps and operator-specific attributes here. | Reconstruct every old column, NULL, empty string and timestamp per operator. Only move a name or type to Customer if conflicting values can be handled without loss. Keep status code and description until a one-to-one mapping is demonstrated. |
| Optional daily list or visit | A list records operator, business date, position and outcome for each entry. A visit records a single attempt and its time. | Add the one needed for resume or reporting. Define repeated entries, retention and access. Preserve the writer’s separate delivery receipts and retry behavior. [Receipt guard](../../src/infrastructure/database/operator_store.py#L550) |

## Phases, proof and rollback

Each phase runs on its own branch and ends with its own activity doc. A phase that changes database code waits for, or comes before, structure Phase R4 (moving the database service), never at the same time.

| Phase | Proposed work and documentation | Accept it when | How to undo or stop |
| --- | --- | --- | --- |
| **DB1 · Write tomorrow’s list on paper** | Record owner answers, a rule glossary and expected labels for day change, month change, an exact tie, prior success, untouched customer and outside-area customer. Distinguish units of stock from customer quota. Record the operator machine’s and the database’s time zone (Q9). Add the dummy example to the repo (Q12). | Owner can read each dummy list and agree on its exact order or on which ties may vary. Record deliberate differences from F120. Another developer repeats the dummy example from the repo. | Edit examples only. |
| **DB2 · Preview on the existing tables** | Catalogue notebook recipes and create a separate read-only preview for each approved operator/area choice. Show eligibility, reason and order. Use the read-only account (Q10) and a read-only transaction. Keep the daily app using its configured list. | Compare labels, duplicates and order with DB1 on dummy tables for both operators, before and after reset. If exact resume is required, demonstrate it across an interruption using a saved list prototype. The preview output is stored nowhere (Q13). | Drop the preview from the pilot. The manual list still works. |
| **DB3 · Design and copy dummy data** | Back up the test instance and time a full restore first. Draw the relationships in the table design above. Map all 14 columns, types, defaults, keys, receipts and existing readers. Write each change as a numbered SQL file with an undo file (Q11). Rehearse copying into separate tables on the local test instance. | Per-operator counts match. Compare old-shaped and reconstructed rows in both directions, including duplicate multiplicity, both operators sharing one identifier, conflicts, missing names, NULL times and stale events. Each undo file restores the old schema exactly, compared with a schema-only export. | Discard the new test copy and retain the originals. Block on any unexplained difference. |
| **DB4 · Prove writes and recovery** | On the test instance only, exercise the existing writer and the proposed writer separately from identical starting data. Document transaction boundaries and who owns startup/reset/replay. Include two operators writing at the same time. | Compare golden files, each committed row and receipt after success, skip, restart, duplicate delivery and a failure halfway. Replay twice without a second quota increment. Re-run DB2 on both copies. | Keep using the existing writer. Do not send the same real sale twice. |
| **DB5 · Measure, then decide on indexes** | Measure the baseline query, then one candidate at a time, on identical dummy data. Try an operator/region key for the shared table or a prefix expression index for the existing predicate. | Record PostgreSQL version, row counts, region/status mix, planner statistics, plans and buffers, median query time and peak memory over ≥5 runs. Include write/reset cost and index size. Result rows and agreed order must match. Keep an index only for a repeatable benefit that meets Q8. | Skip or remove the candidate on the test copy. Keep the baseline and measurements. |
| **DB6 · Optional daily input switch** | Separately approve the new selection rules and any schema cutover. First compare a read-only preview against a manually prepared list. Rehearse restore and document who can switch back. | Explain every membership/order difference, prove same selected inputs give the same outcomes, verify current backlog/receipts survive restart and demonstrate safe fallback before a daily rollout. Require the owner’s explicit go-ahead. | Stop starting new runs. Reconcile in-flight writes and receipts before reverting the reader/writer. Restore the previous input list at a known position. Never replay an uncertain sale. |

**Index suggestion for DB5.** The exported primary key answers an exact identifier lookup. Check the actual plan for `LEFT("NIK"::text, 6)`. A prefix match that selects much of a small table may cost less with a scan. The date-dependent priority still needs evaluation. Keep “today” out of a partial index predicate. Capture `EXPLAIN (ANALYZE, BUFFERS)` on the dummy SELECT and measure process memory separately. **UNVERIFIED** whether any extra index helps here. [Examining query plans](https://www.postgresql.org/docs/18/using-explain.html) · [Expression indexes](https://www.postgresql.org/docs/18/indexes-expressional.html) · [Partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)

## Risks

| Risk | Evidence | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| The preview picks a different list than the owner expects, and nobody notices because the app still runs. | F120, Q1–Q5 | High | High | DB1 examples with exact expected order. DB6 compares with a hand-made list before any switch. |
| “Today” and “this month” mean different days for the app and the query. | F141 | Unknown | High | Record both time zones in DB1. Use one explicit zone in the new design. |
| A schema change cannot be undone. | — | Low | High | Backup and timed restore first, an undo file per change, rehearsal on the test instance only. |
| A preview or a review document shows customer identifiers. | Q13, agent rules §4 | Medium | High | Read-only account, nothing stored, dummy labels in all documents. |
| A second quota increment after a replay or restart. | F122 | Medium | High | DB4 replays twice and compares receipts. |
| Two operators writing at once overwrite each other in a shared table. | F122 | Medium | Medium | DB4 tests concurrent writes before a shared table is adopted. |
| An index slows down writes or the monthly reset more than it speeds up the preview. | F122, DB5 | Medium | Low | DB5 measures write and reset cost and keeps an index only for a repeatable benefit. |
| Database work and the restructuring move the same code in parallel. | Structure plan R4 | Medium | Medium | Never in the same branch or phase. |

## How to check

Evidence date 2026-11-25. Source revision `db5e95a`, Python 3.14.2. The SQL notebook and schema export are the owner’s local reference files. From the project root on the verification machine, these commands identify the revision and repeat the synthetic example. The helper checks the test cluster’s name, data directory, port and major version before executing. It substitutes an in-memory dummy row source for the operator table in the first SELECT. No customer table is read.

```powershell
uv run --locked git rev-parse --short HEAD
uv run --locked python --version
$p=Join-Path $env:LOCALAPPDATA 'TaskBot/phase1-pg18/verification/plans-20261125-db5e95a'
uv run --locked powershell -NoProfile -File (Join-Path $p 'fixture.ps1')
```

```text
DB 127.0.0.1:55432 postgres
cluster=taskbot_phase1 transaction_read_only=on
ordered=old_month_at_5, customer_3, customer_4, customer_5, customer_6, customer_1, customer_2, wait_today
```

To repeat this on another machine, feed the first saved SELECT a dummy row source with the following labels. “Old month” means the day before the first of this month. All entries except `outside` use a synthetic key with the matching prefix. Set the two sale times to NULL and the numeric status code to 0. Print only the ordered labels. The private launcher and the owner’s SQL reference files are local to this checkout.

| Label | Description | Updated | KUOTA / MAX_KUOTA |
| --- | --- | --- | --- |
| customer_1, customer_2 | Completed | Yesterday | 1 / 4 and 1 / 5, respectively |
| customer_3 | Sellable stock unavailable | Yesterday | 0 / 0 |
| customer_4, customer_5, customer_6 | Empty string | Two days ago | 0 / 1, 0 / 2 and 0 / 3 |
| old_month_at_5, old_month_at_6 | Max kuota reached | Old month | 5 / 9 and 6 / 9 |
| wait_today | Sellable stock unavailable | Today | 0 / 0 |
| outside | Empty string | Two days ago | 0 / 0 |
| invalid | Consumer not registered | Two days ago | 0 / 0 |

Live schema inspection, index benchmarking, migration and production preview were **NOT RUN**. They belong to the proposed phases.

This is the original evidence from revision `db5e95a`, kept as it was recorded. For this review, the agent read `fixture.ps1` and `fixture.py` to confirm their safety checks (F140) and did **not** run them again. Revision `741166c` has no change under `src/` since `db5e95a` (`git log --oneline db5e95a..HEAD -- src main.py` prints nothing).

## Open items

- Answer Q1–Q4 and Q9 to start DB1. Q10 and Q13 gate DB2. Q11 gates DB3. The other questions gate their phases.
- **UNVERIFIED:** whether the live schema matches the export (F122). Check it with a schema-only export compared with `db_query/schema backup.sql`.
- **UNVERIFIED:** the time zones of the operator machine and the database session (F141).
- **UNVERIFIED:** whether the dummy example repeats on another machine (F140).
