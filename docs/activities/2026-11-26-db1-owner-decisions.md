# DB1 customer queues and recovery evidence

The owner approved the [selection and recovery decisions](../plans/2026-11-26-plan-owner-questions-and-answers.md). The [SQL example](../../db_query/db1-customer-queue-example.sql) models the agreed order on fictional rows. Revision reviewed: `7605c92`. SQLite 3.50.4.

## How to check

Run from the repository root. SQLite uses an in-memory database with no host.

```powershell
python -c "import sqlite3,pathlib,itertools; rows=sqlite3.connect(':memory:').execute(pathlib.Path('db_query/db1-customer-queue-example.sql').read_text()); print([(s,''.join(r[1] for r in g)) for s,g in itertools.groupby(rows,lambda r:r[0])])"
```

Observed output:

```text
[('month start', 'CABDEF'), ('ordinary', 'CABEF'), ('outside eligible', 'G'), ('restart after C', 'ABDEF')]
```

## F155 · VERIFIED · The dummy queues follow the approved priority order

Markdown checks: `npm.cmd exec --offline -- markdownlint-cli2 docs/activities/2026-11-26-db1-owner-decisions.md "docs/plans/*.md"` and `npm.cmd run --silent lint:md` both reported `Summary: 0 issues in 0 files`.

C is new. A ran out of stock yesterday. B reached the registration request limit yesterday. D reached maximum quota yesterday and waits for the new month. E previously succeeded and F was untouched in the last run. E and F have the same update day, so their fictional identifiers break the tie. Restart assumes a verified final outcome for C. The outside example assumes the inside queue is exhausted and the monthly share permits G. These are inputs to the paper example.

Allocation counts **customers**. For example, six inside customers split three per operator and four outside customers split two per operator. A shared number goes to review. Moving it requires operator and owner approval. The monthly outside share counts **confirmed sales** per operator. The daily stop counts **stock units** per operator. Those three quantities serve different decisions.

## F156 · VERIFIED · Recovery already records an outcome for each delivery event

The journal records an attempt with `INSERT INTO events(id, ready, source, payload)` and a confirmation with `UPDATE events SET ready=2`. The database writer records the event ID and terminal status with `ON CONFLICT (event_id) DO NOTHING` and checks the identity on replay. These references establish local code behavior. A shop-side receipt remains necessary to settle an uncertain remote outcome. [Journal start and confirmation](../../src/infrastructure/database/quota_journal.py#L76) · [Database delivery receipt](../../src/infrastructure/database/operator_store.py#L762)

## Open items

- **PARTIAL.** DB1 exercises ordering locally. The PostgreSQL dummy restart, database session time zone and repeat on a second machine remain unverified. `(Get-TimeZone).Id` returned `SE Asia Standard Time` on the development machine.
- **UNVERIFIED.** The owner observed completion on the page. The timing of server acceptance and the outcome of the individual sale remain unknown. Use the attempt, terminal report and matching Rekap Penjualan entry for reconciliation.
- **Commit gate stopped.** `uv run --locked ruff format --check .` returned `2 files would be reformatted, 163 files already formatted` for existing examples in the quota recovery findings and project structure plan. Later commit gates: NOT RUN.
