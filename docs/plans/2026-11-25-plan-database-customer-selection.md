# Database plan · Who goes next?

- **Start here.** Agree on tomorrow’s list using six imaginary customers. We can check that rule against the current tables before deciding whether to move any data.
- **Already confirmed by the owner.** The first Operator 1 Lowokwaru query is the reference. Customers blocked by monthly quota should get another chance next month. Customers blocked by stock should get another chance the next day. The daily target is 100 stock units per operator, as reported by the owner.
- **Proposed order.** Agree on examples → preview a list in pgAdmin → design simpler tables → rehearse copying and restoring them → measure indexes → consider switching the app’s input. Each step has its own approval and proof below.
- **Open.** The saved query gives some customers priority. It does not remember where yesterday’s operator stopped. DB1–DB5 are proposals. DB6 would change daily operation. [Restructuring plan](2026-11-25-plan-project-structure.md) · [Modernization closeout](2026-11-23-plan-modernization.md)

## Questions and answers

Answer DB-Q1–Q4 first. Examples and suggestions are editable. An open answer is a decision for a future phase.

1. **DB-Q1. Who goes first tomorrow?** Customer 3 hits no stock. Customer 4 was next but never reached. A new customer joins overnight. Should 3 go first, then 4, then the new customer? What if someone else was blocked by monthly quota last month? **A.** The owner wants 3 to get another chance the next day. **Open** for the order of the untouched tail, new arrivals and old monthly cases. The reference SQL places an eligible old monthly case first. Suggest writing down the exact expected list for both examples.
2. **DB-Q2. Which area and operator?** Is each run inside Lowokwaru only, outside only, or inside first and outside after it runs out? Same rule for operator 2? Does the six-digit prefix define membership even if a customer moves? **A. Open.** Suggest an explicit choice per operator. The notebook headings disagree with two filters (F121).
3. **DB-Q3. Who can come back?** May a completed customer reappear the next day or the same day? Should today’s no-stock or this month’s max-quota rows stay at the bottom or disappear until eligible? Keep all five blocked descriptions excluded? **A. Open.** Suggest displaying waiting and excluded reasons separately in a preview so the operator can see which list they would actually use.
4. **DB-Q4. Where are the quota and date boundaries?** Include quota exactly 5? What about 6 from last month, before the monthly reset? Is midnight Jakarta time the cutoff? Use the last status update or a recorded attempt time? **A. Open.** The saved query includes 5 and reads the row’s update date. The app also has a separate monthly reset (F120, F122). Agree on before-reset, after-reset, midnight and month-end examples.
5. **DB-Q5. When do we stop and resume?** Stop on the first no-stock result, after 100 confirmed units, or whichever comes first? If the app restarts, should that same customer be first? How should ties, newly added customers, repeat inputs or simultaneous operators be handled? **A. Open.** Suggest keeping today’s stop-on-stock outcome during comparison. A daily list with saved positions is an option if yesterday’s exact order matters.
6. **DB-Q6. What belongs to a customer and what belongs to the operator?** Can two operators share the same person but have different quota, name, type or status? Can an identifier begin with zero? Which value wins when two records disagree? Who can correct it? **A. Open.** Suggest preserving both source rows exactly until these rules are agreed. Keep identifiers out of documents and logs used for the review.
7. **DB-Q7. How much history is needed?** Latest state and last two sale times, every attempt, or a daily queue with unfinished positions? Who may view it and how long should it stay? Are old schemas, pgAdmin queries, spreadsheets or exports used elsewhere? **A. Open.** Suggest keeping existing readers working and adding history only for a named need. A delivery receipt answers whether a write was applied. It is a different record from a customer visit.
8. **DB-Q8. What would justify an index?** What row counts, operator mix, typical region size, peak memory and acceptable preview time should we test? Who approves switching inputs and who can switch back? **A. Open.** Suggest dummy distributions and a repeatable timed comparison first. The owner’s 100-unit target describes available stock, not table size or a query limit.

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

## Proposed table design

Start with a read-only query over today’s tables. It is the cheapest way to check DB-Q1–Q5 and can be discarded independently. A second option is one shared state table keyed by operator and customer. It avoids one table definition per operator. A third option separates shared identity, operator state and optional visit history. Choose that design only after DB-Q6–Q7 establish which facts really are shared (F122).

| Proposed record | Key and meaning | What to prove before adopting it |
| --- | --- | --- |
| Operator | One stable operator ID. Keep a mapping to the existing suffix and display name. | Renaming a display name cannot merge accounts. |
| Customer | One internal customer ID and a unique external number *if* the owner confirms that identity rule. | Review conflicts using aggregate counts. A bigint export cannot tell us whether a leading zero was lost before import. Define the input format before converting it. |
| Operator customer state | One row per `(operator_id, customer_id)`. Keep quota, peak quota, status, problem/conflict, timestamps and operator-specific attributes here. | Reconstruct every old column, NULL, empty string and timestamp per operator. Only move a name or type to Customer if conflicting values can be handled without loss. Keep status code and description until a one-to-one mapping is demonstrated. |
| Optional daily list or visit | A list records operator, business date, position and outcome for each entry. A visit records a single attempt and its time. | Add the one needed for resume or reporting. Define repeated entries, retention and access. Preserve the writer’s separate delivery receipts and retry behavior. [Receipt guard](../../src/infrastructure/database/operator_store.py#L550) |

## Phases, proof and rollback

| Phase | Proposed work and documentation | Accept it when | How to undo or stop |
| --- | --- | --- | --- |
| **DB1 · Write tomorrow’s list on paper** | Record owner answers, a rule glossary and expected labels for day change, month change, an exact tie, prior success, untouched customer and outside-area customer. Distinguish units of stock from customer quota. | Owner can read each dummy list and agree on its exact order or on which ties may vary. Record deliberate differences from F120. | Edit examples only. |
| **DB2 · Preview on the existing tables** | Catalogue notebook recipes and create a separate read-only preview for each approved operator/area choice. Show eligibility, reason and order. Keep the daily app using its configured list. | Compare labels, duplicates and order with DB1 on dummy tables for both operators, before and after reset. If exact resume is required, demonstrate it across an interruption using a saved list prototype. | Drop the preview from the pilot. The manual list still works. |
| **DB3 · Design and copy dummy data** | Draw the relationships above. Map all 14 columns, types, defaults, keys, receipts and existing readers. Rehearse copying into separate tables on the local test instance. | Per-operator counts match. Compare old-shaped and reconstructed rows in both directions, including duplicate multiplicity, both operators sharing one identifier, conflicts, missing names, NULL times and stale events. Restore the old schema from a backup in a clean test DB. | Discard the new test copy and retain the originals. Block on any unexplained difference. |
| **DB4 · Prove writes and recovery** | On the test instance only, exercise the existing writer and the proposed writer separately from identical starting data. Document transaction boundaries and who owns startup/reset/replay. | Compare golden files, each committed row and receipt after success, skip, restart, duplicate delivery and a failure halfway. Replay twice without a second quota increment. Re-run DB2 on both copies. | Keep using the existing writer. Do not send the same real sale twice. |
| **DB5 · Measure, then decide on indexes** | Measure the baseline query, then one candidate at a time, on identical dummy data. Try an operator/region key for the shared table or a prefix expression index for the existing predicate. | Record PostgreSQL version, row counts, region/status mix, planner statistics, plans and buffers, median query time and peak memory over ≥5 runs. Include write/reset cost and index size. Result rows and agreed order must match. Keep an index only for a repeatable benefit that meets DB-Q8. | Skip or remove the candidate on the test copy. Keep the baseline and measurements. |
| **DB6 · Optional daily input switch** | Separately approve the new selection rules and any schema cutover. First compare a read-only preview against a manually prepared list. Rehearse restore and document who can switch back. | Explain every membership/order difference, prove same selected inputs give the same outcomes, verify current backlog/receipts survive restart and demonstrate safe fallback before a daily rollout. Require the owner’s explicit go-ahead. | Stop starting new runs. Reconcile in-flight writes and receipts before reverting the reader/writer. Restore the previous input list at a known position. Never replay an uncertain sale. |

**Index suggestion for DB5.** The exported primary key answers an exact identifier lookup. Check the actual plan for `LEFT("NIK"::text, 6)`. A prefix match that selects much of a small table may cost less with a scan. The date-dependent priority still needs evaluation. Keep “today” out of a partial index predicate. Capture `EXPLAIN (ANALYZE, BUFFERS)` on the dummy SELECT and measure process memory separately. **UNVERIFIED** whether any extra index helps here. [Examining query plans](https://www.postgresql.org/docs/18/using-explain.html) · [Expression indexes](https://www.postgresql.org/docs/18/indexes-expressional.html) · [Partial indexes](https://www.postgresql.org/docs/18/indexes-partial.html)

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

## Open items

Answer DB-Q1–Q4 to start DB1. The remaining questions become gates before the corresponding phases.
