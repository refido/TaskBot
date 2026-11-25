# Database plan · Who goes next?

- **Goal.** Let the database choose tomorrow’s customer list instead of a hand-made list, without changing what a run does with the list it gets.
- **Owner answers recorded (2026-11-26).** Q1–Q13 are answered. The [agreed rules](#rules-agreed-with-the-owner) turn them into one ordering, and the [proposed selection formula](#proposed-selection-formula) answers your request for a better formula.
- **New questions.** Your answers raised Q14–Q24. Most are about the order of the first buckets, the anomaly rule, the share outside Lowokwaru and restart. Two answers conflict with the saved query or with today’s code ([F145](#f145--verified--the-saved-query-and-the-owners-month-start-example-disagree), [F144](#f144--partial--a-restarted-run-does-not-read-the-earlier-runs-itemsjsonl)).
- **Status.** No database or code change yet. DB1 (rules and dummy examples, documentation only) can start now and will absorb Q14–Q24. DB6 would change daily operation and needs your explicit go-ahead.
- **Related.** [Project structure plan](2026-11-25-plan-project-structure.md) (the database code moves in its Phase R4) · [Modernization plan](2026-11-23-plan-modernization.md)

## Waiting on the owner

### Not finished

- DB1–DB6 are proposals. None has started.
- The saved query gives some customers priority. It does not remember where yesterday’s operator stopped ([F120](#f120--verified--eligibility-comes-before-priority)).
- Two area headings disagree with their filters ([F121](#f121--verified--two-area-labels-disagree-with-their-filters)).
- The repeatable example runs on one machine only ([F140](#f140--partial--the-dummy-example-can-be-repeated-on-one-machine-only)).
- `db_query/deduplicate.sql` is referenced in Q6 but not reviewed yet. Review it in DB1 without printing any row.

### Questions

Answered: Q1–Q13. Open:

- [Q14 · New customers or yesterday’s out-of-stock customer first?](#questions-and-answers)
- [Q15 · On the first day of a month, out-of-stock or maximum quota first?](#questions-and-answers)
- [Q16 · Exactly when is a customer an anomaly, and who brings them back?](#questions-and-answers)
- [Q17 · How is the share outside Lowokwaru counted, and what happens at the limit?](#questions-and-answers)
- [Q18 · Where does each customer’s monthly limit come from?](#questions-and-answers)
- [Q19 · Does the reset to 0 need its own job at 00:00, or is “treat as 0” enough?](#questions-and-answers)
- [Q20 · Should a restarted run skip customers already processed today?](#questions-and-answers)
- [Q21 · Is “once a month” a goal or just what oldest-first gives?](#questions-and-answers)
- [Q22 · Can one customer number appear in both operator tables?](#questions-and-answers)
- [Q23 · Where does the anomaly history live if files are archived every January?](#questions-and-answers)
- [Q24 · Is this index rule acceptable?](#questions-and-answers)

### Confirmations

- Confirm that the app keeps reading the configured customer list until DB6 is approved.
- Confirm that every schema change is first rehearsed on the local test instance, with a backup and a restore, before any real database is touched.
- Confirm that “100 stock units per operator” is a daily stop target, not a limit on how many rows the preview returns (Q5, Q8).
- Confirm the [proposed selection formula](#proposed-selection-formula) as the starting point for DB1’s dummy examples.
- **Confirmed by the owner (2026-11-26):** the database plan and the project structure plan never change the same code in the same branch or phase.

## Questions and answers

Each question has a suggested answer. Replace `*open*` with your answer, or write “agree” to take the suggestion. Q1–Q8 were called DB-Q1–DB-Q8 before. Their numbers did not change. Q14–Q24 come from the owner’s answers to Q1–Q13.

- **Q1 · Who goes first tomorrow?** Customer 3 hits no stock. Customer 4 was next but never reached. A new customer joins overnight. Should 3 go first, then 4, then the new customer? What if someone else was blocked by monthly quota last month? **Owner answer so far:** customer 3 gets another chance the next day. **Still open:** the order of the untouched tail, new arrivals and old monthly cases. The reference query puts an eligible old monthly case first. **Suggested answer:** write down the exact expected list for both examples in DB1. **Owner answer:** The flow is like this: For daily operations, priority is given to customers who encountered an "out-of-stock" status on the previous day. For example:

Day 1: 1, 2, 3, 4, 5, ..., 10,000 (Customer 5 hits "out-of-stock")
Day 2: 5, 6, 7, 8, 9, ..., 10,000 (Customer 9 hits "out-of-stock")
Day 3: 9, 10, 11, 12, 13, ..., 10,000 (Customer 13 hits "out-of-stock")
This process continues in a loop, ordered from customers who have not been updated for the longest time to those most recently updated.

At the turn of the month:
Day 31: 9, 10, 11, 12, 13, ..., 10,000 (Customer 13 hits "out-of-stock")
Day 1: 13, 14, 15, 16, 17, ..., 10,000 (Customer 17 hits "out-of-stock")

If many customers hit the "maximum quota" limit in the previous month, the sequence would look like this:
Month 1, Day 31: 1, 2, 3, 4, 5, ..., 20, 21, 22, ..., 10,000 (Customers 3, 4, and 5 hit the "maximum quota"; Customer 20 hits "out-of-stock")
Month 2, Day 1: 20, 3, 4, 5, 21, 22, ..., 10,000 (Customers 3, 4, and 5 hit the "maximum quota"; Customer 20 hits "out-of-stock")

The objective is to identify or filter customers who consistently hit the "maximum quota" every month. Since it should not be possible for a customer to have a quota of zero while simultaneously being flagged for hitting the "maximum quota," any customer who hits this limit for 3 to 6 consecutive months—without ever successfully completing a transaction—will be flagged as an anomaly. Such customers will then be removed from the daily processing queue to prevent them from hindering the daily workflow.

Why is the "maximum quota" prioritized at the beginning of the month? Prioritizing it every single day would disrupt other, regular customers.

If you can come up with a better formula or approach, feel free to propose it.

- **Q2 · Which area and operator?** Is each run inside Lowokwaru only, outside only, or inside first and outside once the inside list runs out? Is it the same rule for operator 2? Does the six-digit prefix define membership even if a customer moves? **Suggested answer:** an explicit choice per operator. The notebook headings disagree with two filters (F121). **Owner answer:** There are two options available: the primary (and default) option, which utilizes the Lowokwaru source, and a second option, which covers sources outside of Lowokwaru.

The choice of which option to use depends on the user, client, or individual. Each customer is subject to a maximum processing quota of four times per month (though the specific maximum quota may vary by customer—some may have a limit of eight, while others may reach their limit at just one). Therefore, if all available sources within the Lowokwaru list have already been exhausted for a given customer within a month, the second option may be used. However, this is subject to the condition that the percentage of processes handled outside of Lowokwaru must not exceed 30%, with an absolute upper limit of 50%; the monthly processing volume must remain predominantly driven by the Lowokwaru source.

Currently, the identification of whether a customer belongs to the Lowokwaru category or otherwise is based on the aforementioned six-digit prefix. Even if a customer is physically located outside of Lowokwaru, they are still classified as being within the Lowokwaru category as long as their prefix matches the criteria.

- **Q3 · Who can come back?** May a completed customer reappear the next day or the same day? Should today’s no-stock or this month’s max-quota rows stay at the bottom, or disappear until they are eligible? Keep all five blocked descriptions excluded? **Suggested answer:** show waiting and excluded reasons separately in the preview, so you can see which list you would actually use. **Owner answer:** All entries can be included; since the sequence is based on the `last_updated` timestamp, they should be distributed evenly—perhaps with each customer appearing once a month. For example:

Customer 1, last updated 2026-11-01
Customer 2, last updated 2026-11-02
Customer 3, last updated 2026-11-03
Customer 4, last updated 2026-11-04
Customer 5, last updated 2026-11-05

In this case, the sequence would simply be: Customer 1, Customer 2, Customer 3, Customer 4, Customer 5.

If, however, the data is as follows:

Customer 1, last updated 2026-10-01
Customer 2, last updated 2026-11-02
Customer 3, last updated 2026-11-25
Customer 4, last updated 2026-09-04
Customer 5, last updated 2026-12-05

Then the sequence would be: Customer 1, Customer 4, Customer 2, Customer 3, Customer 5.

- **Q4 · Where are the quota and date boundaries?** Include quota exactly 5? What about 6 from last month, before the monthly reset? Use the last status update or a recorded attempt time? **Suggested answer:** agree on before-reset, after-reset, midnight and month-end examples. The saved query includes 5 and reads the row’s update date. The app also has a separate monthly reset (F120, F122). The clock question is now Q9. **Owner answer:** The quota should reset to 0 at the end of each month at 00:00; from 00:01 onwards, the quota for every customer number must be 0, without exception.

`max_quota` represents the upper limit of the quota available to each customer. This value can vary; for instance, if the quota for the first month is 3, then `max_quota` is 3. If the quota for the following month is 7, then `max_quota` becomes 7. If the quota for the third month is 2, `max_quota` remains 7, as that is the highest quota the customer has ever reached.

However, according to the rules, the quota is capped at 4 per month; therefore, under normal circumstances, `max_quota` should be 4 or 5.

- **Q5 · When do we stop and resume?** Stop on the first no-stock result, after 100 confirmed units, or whichever comes first? If the app restarts, should the same customer be first? How should ties, newly added customers, repeat inputs or two operators at once be handled? **Suggested answer:** keep today’s stop-on-stock behavior during the comparison. Add a daily list with saved positions only if yesterday’s exact order matters. **Owner answer:** *Ya, masih menggunakan behavihour yang sekarang.

belum menemukan ide yang lebih baik dari behaviour yang sekarang, mungkin kamua ada ide?

jika ada data baru, maka data tersebut diprioritaskan diproses awal, baru lanjut ke proses yang seperti biasanya (dari yang paling lama belum di updated)

jika app restart, perlu di cek apakah customer tersebut sudah muncul status/flagnya (sukses, fa), jika sudah maka melanjutkan ke customer berikutnya, jika belum maka ulangi dari yang belum mendapat status/flagnya. Itulah gunanya item.jsonl dimana jika sudah ada di dalam file, maka kemungkinan besar sudah terproses status/flagnya.

- **Q6 · What belongs to a customer and what belongs to the operator?** Can two operators share the same person but have different quota, name, type or status? Can an identifier begin with zero? Which value wins when two records disagree? Who can correct it? **Suggested answer:** keep both source rows exactly as they are until these rules are agreed. Keep identifiers out of documents and logs used for the review. **Owner answer:** no, tidak boleh ada duplicate customer, bisa cek referensi berikut untuk mengatasi duplikasi db_query\deduplicate.sql

identifier utama hanya customer number yang benar benar unik

- **Q7 · How much history is needed?** The latest state and the last two sale times, every attempt, or a daily queue with unfinished positions? Who may view it and how long should it stay? Are old schemas, pgAdmin queries, spreadsheets or exports used elsewhere? **Suggested answer:** keep existing readers working and add history only for a named need. A delivery receipt answers whether a write was applied. It is a different record from a customer visit. **Owner answer:** Data is typically archived on an annual basis; for instance, once December 31, 2025, has passed, all history from 2025 will be archived (compressed into a .rar or .zip file) on the following day, January 1, 2026.

For example, if today’s date is November 26, 2026, the data from January 1, 2026, through November 26, 2026, remains accessible.

The previous scheme—involving pgAdmin queries, spreadsheets, or exports—is not currently being used anywhere outside of this specific project/workspace.

- **Q8 · What would justify an index?** What row counts, operator mix, typical region size, peak memory and acceptable preview time should we test? Who approves switching inputs and who can switch back? **Suggested answer:** dummy distributions and a repeatable timed comparison first. The owner’s 100-unit target describes available stock, not table size or a query limit. **Owner answer:** I’m not entirely sure—what would be the best approach here? The goal of indexing, as it stands, is to improve performance or at least ensure things don’t run too slowly. If there’s no significant improvement, then there’s no need for indexing; otherwise, it will just end up as "junk" or an unused index.

- **Q9 · Which clock decides “today”?** The app writes `UPDATED_TIME` in the operator machine’s local time, without a time zone. The saved query compares it with PostgreSQL’s `CURRENT_DATE`, which follows the database session’s time zone ([F141](#f141--partial--the-app-and-the-saved-query-may-use-different-clocks)). If the two differ, “yesterday” and “last month” move. Options: (a) both use Asia/Jakarta explicitly, (b) both use the operator machine’s time zone, (c) leave it as it is and check that they match. **Suggested answer:** (c) now, by recording both settings in DB1. Choose (a) for the new design in DB3, because it does not depend on a machine setting. **Owner answer:** *using the WIB (Asia/Jakarta) time zone*
- **Q10 · Which database account may the preview use?** **Suggested answer:** a separate account that can only read the operator tables (`SELECT` only), with the preview running inside a read-only transaction. The app’s writing account is not used for previews. Creating a role is a database change, so it is rehearsed on the test instance first. **Owner answer:** *Yes, as suggested.*
- **Q11 · How are schema changes written and undone?** Options: (a) numbered plain SQL files in the repo, each with a matching undo file, run by hand in pgAdmin or `psql`, (b) a migration tool such as Alembic, which is a new dependency. **Suggested answer:** (a). It needs no new dependency and is easy to read. Every file is rehearsed on the test instance: backup → apply → check → undo → check. **Owner answer:** *Yes, as suggested. Option A*
- **Q12 · Where does the repeatable dummy example live?** Today it is a private script on one machine ([F140](#f140--partial--the-dummy-example-can-be-repeated-on-one-machine-only)). **Suggested answer:** in DB1, add the dummy rows as a SQL file and a pytest test that uses the existing test-database settings. They hold dummy labels only, never real query results, so the next developer can repeat the example. **Owner answer:** *Yes, as suggested.*
- **Q13 · Who may see the preview list?** The preview shows identifiers and names of real customers. **Suggested answer:** only the operator, on their own machine. The preview is never written to a report file, a log, the repo or the future API. Documents show counts and dummy labels only. **Owner answer:** *Yes, as suggested.*

**Follow-up questions from the owner’s answers (2026-11-26).**

- **Q14 · New customers or yesterday’s out-of-stock customer first?** Q5 says new customers go first. Q1 says the customer who hit out-of-stock yesterday goes first. Both cannot be first. How do we recognise a “new” customer: a row with no status and no sale time, or a row created since the last run? **Suggested answer:** new customers first, then yesterday’s out-of-stock customer. A “new” customer is a row with no `LAST_TRANSACTION_TIME` and an empty status description. **Owner answer:** *open*
- **Q15 · On the first day of a month, out-of-stock or maximum quota first?** Your example (“Month 2, Day 1: 20, 3, 4, 5, 21 …”) puts the out-of-stock customer before last month’s maximum-quota customers. The saved query does the opposite ([F145](#f145--verified--the-saved-query-and-the-owners-month-start-example-disagree)). **Suggested answer:** follow your example. The DB2 preview uses your order, and the saved query in `db_query/` stays as it is for reference. **Owner answer:** *open*
- **Q16 · Exactly when is a customer an anomaly, and who brings them back?** You wrote “3 to 6 consecutive months”. What counts as hitting the maximum quota in a month: the “Max kuota reached” status at least once in that calendar month? What counts as a successful transaction: a confirmed sale (`KUOTA` went up)? **Suggested answer:** a customer is an anomaly after **3** consecutive calendar months (WIB) with at least one “Max kuota reached” status and **no** confirmed sale in any of those months. An anomaly is excluded from the list and shown in a separate review list. Only the owner can bring a customer back. Start with 3 and change the number later if it removes too many customers. **Owner answer:** *open*
- **Q17 · How is the share outside Lowokwaru counted, and what happens at the limit?** You set a target of 30% and a hard limit of 50%. **Suggested answer:** count confirmed sales per operator per calendar month (WIB). The outside list is used only when the day’s eligible Lowokwaru list is empty. Below 30% it is used freely. From 30% to 50% the preview shows a warning. At 50% the outside list is not offered for the rest of the month. Who chooses the outside option: the operator each day, or a setting per operator? **Owner answer:** *open*
- **Q18 · Where does each customer’s monthly limit come from?** Q2 says the limit is usually 4 a month, but can be 8 or 1. Q4 says it is capped at 4 and `MAX_KUOTA` is normally 4 or 5. The tables have no column for a per-customer limit: `MAX_KUOTA` is the highest quota ever reached ([F146](#f146--verified--the-code-matches-the-owners-meaning-of-max_kuota-and-resets-quota-at-app-start)). The saved query allows `KUOTA` up to 5. **Suggested answer:** the shop decides the limit and tells us with the “Max kuota reached” status. The database does not store the limit. Keep the saved query’s `KUOTA <= 5` filter until you choose a different number. **Owner answer:** *open*
- **Q19 · Does the reset to 0 need its own job at 00:00, or is “treat as 0” enough?** Today the reset runs each time the app starts and sets last month’s quota to 0 ([F146](#f146--verified--the-code-matches-the-owners-meaning-of-max_kuota-and-resets-quota-at-app-start)). A preview run on the 1st before the app starts still sees last month’s numbers. **Suggested answer:** no scheduled job. The preview treats any quota last updated before 00:00:00 WIB on the 1st as 0, which matches what the app sets when it starts. The boundary is exactly 00:00:00, so there is no gap between 00:00 and 00:01. **Owner answer:** *open*
- **Q20 · Should a restarted run skip customers already processed today?** You expect a restart to skip customers already in `items.jsonl`. Each run writes into a new folder, and no code was found that reads an earlier run’s `items.jsonl` ([F144](#f144--partial--a-restarted-run-does-not-read-the-earlier-runs-itemsjsonl)). **Suggested answer:** first confirm what happens today with one dummy restart in the local shop. With a database list, the list itself skips customers with a final status updated today, so no file needs to be read. That is new behavior and belongs in DB6. **Owner answer:** *open*
- **Q21 · Is “once a month” a goal or just what oldest-first gives?** With 10,000 customers and about 100 sales a day per operator, one pass through the list takes about 100 days. Oldest-first therefore reaches each customer less than once a month. **Suggested answer:** oldest-first only, with no once-a-month promise. **Owner answer:** *open*
- **Q22 · Can one customer number appear in both operator tables?** You wrote that there must be no duplicate customer. Does that mean once per operator table, or once across both operators? **Suggested answer:** once per operator table, which is what the primary key enforces today. A customer in both tables is allowed, but the preview reports how many there are. **Owner answer:** *open*
- **Q23 · Where does the anomaly history live if files are archived every January?** The anomaly rule needs several past months. In January, February and March those months fall partly in the previous year, which is archived on 1 January. **Suggested answer:** a small monthly summary table in the database (operator, customer, month, max-quota-hit yes/no, confirmed sales count), which is not archived. The report files are archived once a year, as today. **Owner answer:** *open*
- **Q24 · Is this index rule acceptable?** You asked for the best approach. **Suggested answer:** measure on dummy data of realistic size (10,000 rows per operator). Keep an index only if the preview’s median time improves by at least 30% **and** by at least 50 ms over 5 runs, while writes and the monthly reset get no more than 10% slower. Otherwise, drop it and record the numbers. **Owner answer:** *open*

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

## F144 · PARTIAL · A restarted run does not read the earlier run’s `items.jsonl`

Every run gets its own folder, named from a timestamp and four random hex characters:

```python
# src/application/dto/run_context.py:L76-L83
resolved_suffix = suffix or uuid.uuid4().hex[:4]
...
run_id = f"{timestamp:%Y%m%d_%H%M%S}_{resolved_suffix}"
```

The reporter creates `items.jsonl` inside that folder ([reporter.py:963](../../src/web/reporter.py#L963)). The only reader of `jsonl_path` outside the file writer is the database sync, for the same run ([report_syncer.py:55](../../src/infrastructure/database/report_syncer.py#L55)). No reader of an earlier run’s file was found. **PARTIAL:** a `grep` for `jsonl_path` is evidence that the code does not do this, but not proof. Whether a restart re-processes customers today is **UNVERIFIED**. Check it with one dummy restart in the local shop (Q20).

## F145 · VERIFIED · The saved query and the owner’s month-start example disagree

In the saved query, last month’s “Max kuota reached” rows are priority 0, and “Sellable stock unavailable” from before today is priority 1 (F120). The owner’s example for the first day of a month is “20, 3, 4, 5, 21 …”, with 20 the out-of-stock customer and 3–5 the maximum-quota customers. That puts out-of-stock first. On the 1st, the saved query would return 3, 4, 5, 20. [Saved query priorities](<../db_query/basic query.sql#L28>) (Q15)

## F146 · VERIFIED · The code matches the owner’s meaning of `MAX_KUOTA` and resets quota at app start

`MAX_KUOTA` keeps the highest quota reached, as the owner described in Q4:

```sql
-- src/infrastructure/database/_operator_sql.py:L113-L115
WHEN EXCLUDED.{kuota} > 0
    THEN GREATEST(target.{max_kuota}, {next_kuota})
ELSE GREATEST(target.{max_kuota}, target.{kuota})
```

Last month’s quota is set to 0 when the app sets up the database, which happens at every start, not at midnight:

```python
# src/infrastructure/database/operator_store.py:L358-L360
self.ensure_database_exists()
self.ensure_tables_exist()
self.reset_monthly_quotas()
```

The reset sets `KUOTA = 0` where `date_trunc('month', UPDATED_TIME)` is before the current month ([reset](../../src/infrastructure/database/operator_store.py#L468)). Revision `974451c`. (Q18, Q19)

## Rules agreed with the owner

From Q1–Q13 (2026-11-26). Times are WIB (Asia/Jakarta).

| Rule | Owner’s answer |
| --- | --- |
| Area | Lowokwaru (six-digit prefix) is the default source. Outside Lowokwaru is a second option, used only when Lowokwaru is exhausted. It should stay at or below 30% of the month, and never above 50%. The prefix decides, not where the customer lives. (Q2) |
| Order | Oldest `UPDATED_TIME` first, so every customer comes around in turn. (Q3) |
| Out-of-stock | The customer who hit out-of-stock yesterday is first the next day, because the run stopped there. (Q1) |
| New customers | New data is processed first, then the usual order. (Q5) |
| Maximum quota | Customers who hit the maximum quota last month come early on the first day of the new month only. Doing it every day would disrupt regular customers. (Q1) |
| Anomaly | A customer who hits the maximum quota for 3–6 months in a row without one successful sale is flagged and removed from the daily list. (Q1) |
| Quota | Quota is 0 for everyone from the start of each month. `MAX_KUOTA` is the highest quota ever reached. The normal cap is 4 a month. (Q4) |
| Stop | Today’s stop-on-stock behavior stays. (Q5) |
| Restart | Do not process again a customer who already has a final status. (Q5) |
| Identity | No duplicate customers. The customer number is the only identifier. (Q6) |
| History | Report history is archived once a year, on 1 January. Old pgAdmin queries, spreadsheets and exports are not used outside this project. (Q7) |
| Clock | WIB, Asia/Jakarta. (Q9) |
| Safety | Read-only preview account (Q10), numbered SQL files with undo files (Q11), dummy example in the repo (Q12), preview visible to the operator only (Q13). |

## Proposed selection formula

You asked for a better formula. This one combines all the rules above into one sort key. It needs no extra state except the anomaly history (Q23). Every eligible row of one operator gets a **bucket**, and the list is sorted by bucket, then by oldest `UPDATED_TIME`, then by customer number. The customer number is the last key so that ties always come out in the same order (F120 found no unique last key).

| Bucket | Who | When |
| --- | --- | --- |
| 0 | New customers: no sale time and no status yet (Q14) | Every day |
| 1 | “Sellable stock unavailable”, last updated before today | Every day |
| 2 | “Max kuota reached”, last updated before this month, not an anomaly | First processing day of the month only (Q15). On other days these customers fall into bucket 3. |
| 3 | Every other eligible customer | Every day |
| — | Excluded: the five blocked descriptions, anomalies (Q16), customers with a final status updated today (Q20), customers over the quota filter (Q18) | Shown in a separate review list, never processed |

Area is a filter on top of the buckets. The Lowokwaru list is built first. The outside list is offered only when the Lowokwaru list is empty and the month’s outside share allows it (Q17).

Why this is better than special cases in many queries:

- **One query per operator and area.** The bucket is a single `CASE` expression, so today’s two dozen notebook variants (F121) can shrink to one parameterized preview.
- **Resuming needs no saved position.** The out-of-stock customer moves to the front through bucket 1. Everyone after them still has an older `UPDATED_TIME` than the customers served yesterday.
- **The month start rule fires once.** It is tied to “first processing day of the month”, not to “day 1”, so a month that starts on a day off still gets it.
- **Stable and testable.** Each DB1 dummy example becomes a short table of rows → expected labels.

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

- Answer Q14–Q24. They become the rules and dummy examples of DB1.
- **UNVERIFIED:** whether the live schema matches the export (F122). Check it with a schema-only export compared with `db_query/schema backup.sql`.
- **UNVERIFIED:** whether the operator machine and the database session both use WIB (F141, Q9). Check with `Get-TimeZone` and `SHOW TimeZone;`.
- **UNVERIFIED:** whether the dummy example repeats on another machine (F140).
- **UNVERIFIED:** whether a restart re-processes customers today (F144, Q20).
