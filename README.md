# TaskBot

TaskBot automates the complete LPG customer-sale workflow in a Playwright browser. It supports multiple operators and NIKs, handles optional customer onboarding states, solves the transaction puzzle, writes durable reports, and can synchronize terminal outcomes to PostgreSQL.

## Features

- Multi-account and multi-NIK execution with one isolated browser per account.
- Login, session probes, automatic re-login, and bounded session recovery.
- `Catat Penjualan` navigation and robust zero-stock confirmation: three checks, with a dashboard refresh before the final check. Confirmed empty stock stops only the affected account.
- State-driven customer prechecks that use bounded known-UI-state waits after NIK submission and every action instead of assuming a fixed sequence or depending on `networkidle`.
- Customer-type selection preferring `Rumah Tangga`, then `Usaha Mikro`, then the first usable semantic radio option.
- NIK autocomplete dismissal before `LANJUTKAN PENJUALAN`, preventing a same-NIK suggestion portal from covering the normal button without force-clicking through real dialogs.
- Distinct Usaha Mikro NIB reminder handling, identified by its NIB-specific message and continued once without treating it as an incomplete customer-data update.
- Optional `Pernyataan Persetujuan` handling with one `SELANJUTNYA` click.
- Automatic customer-data updates from the canonical local NIK parser.
- One application-wide, thread-safe customer-update pacer. Opening the form,
  submitting it, confirming it, and restarting the same NIK cannot burst across
  concurrently running operators; this channel is independent of skip pressure.
- Same-NIK restart after update success. It consumes no general-error retry, session retry, or skip-rate quota and creates no extra terminal row.
- Infinite-update protection: one automatic update and one same-NIK recheck per NIK.
- Existing terminal handling for under-17 NIKs, unregistered customers, invalid registered NIKs, base restrictions, unusual cross-base transactions, and the per-NIK daily registration-request limit. That blocker requires the exact title `Tidak Dapat Melanjutkan Pendaftaran Pelanggan` together with its retry-next-day message; it is closed once with `Tutup`, recorded as `skipped_registration_request_limited`, and never retried that day.
- Transaction blocker handling before and after `CEK PESANAN`: the exact monthly unreasonable-purchase warning is recorded as maximum quota, while zero sellable stock stops the affected account.
- Puzzle solving with bounded attempts, challenge-refresh detection, retry telemetry, and debug image artifacts.
- Bounded general-error retries, per-NIK session recovery, analytics, operator summaries, and optional PostgreSQL synchronization.
- One shared run ID and report root per application execution, with stable safe
  operator IDs such as `operator_01` across logs, reports, DB telemetry, and artifacts.
- Immediate local terminal-row durability and a one-row PostgreSQL commit attempt
  for every terminal NIK before processing advances.
- Configurable NIK masking. Authentication credentials, cookies in logs, and
  registered runtime secrets are always redacted.

## Customer workflow overview

After TaskBot submits a NIK, the precheck service resolves one of these typed states:

```text
SESSION_EXPIRED, UNDER_17, CUSTOMER_TYPE, NIB_REMINDER, CONSENT,
UPDATE_REQUIRED, UPDATE_FORM,
UPDATE_CONFIRMATION, UPDATE_SUCCESS, TRANSACTION_READY, NOT_REGISTERED,
REGISTRATION_REQUEST_LIMITED, INVALID_REGISTERED_NIK,
CANNOT_TRANSACT_AT_BASE, UNUSUAL_TRANSACTION, UNKNOWN
```

When states briefly overlap, the resolver prioritizes session expiry, existing blockers, update success, confirmation, update form, update required, consent, the NIB reminder, customer type, and finally transaction readiness. After a one-shot action it excludes the previous state while waiting, so a stale consent, NIB reminder, or customer-type marker cannot hide the newly rendered state. Session expiry returns to the existing bounded session-recovery path.

It returns `CONTINUE`, `SKIP`, or `RESTART_AFTER_UPDATE`. A typical update path is:

```text
NIK
-> optional customer type
-> optional consent
-> update required
-> update form
-> confirmation
-> update success
-> dashboard
-> SAME NIK
-> normal transaction
```

All of these paths are valid before the normal transaction and puzzle stages:

```text
NIK -> transaction -> puzzle
NIK -> customer type -> transaction -> puzzle
NIK -> consent -> transaction -> puzzle
NIK -> customer type -> consent -> transaction -> puzzle
NIK -> customer type -> consent -> update -> SAME NIK -> transaction -> puzzle
NIK -> consent -> update -> SAME NIK -> transaction -> puzzle
```

Mutation buttons are single-shot, and the precheck service—not the individual action component—resolves what appears after consent, NIB continuation, update submission, or confirmation. TaskBot never silently falls back to `NANTI SAJA, LANJUT PENJUALAN` after an update failure. Missing form, confirmation, success, dashboard return, or a repeated update request becomes a terminal error for that NIK.

Known unhappy paths use semantic text or roles rather than generated Mantine/CSS hashes: under-17, unregistered customer, invalid registered NIK, base restriction, unusual cross-base transaction, the distinct Usaha Mikro NIB reminder, the exact daily registration-request limit, monthly purchase limit, zero stock, and the exact failed-puzzle title. The daily-limit state has terminal priority even when it overlaps an update form, confirmation, or success screen; it maps to database status `429` with zero quota delta. A blocker that disappears between detection and handling is resolved again; it cannot silently skip a NIK without a terminal report.

## Complete workflow catalogue

TaskBot treats the customer pages as a state machine, not as one fixed page
sequence. Its precheck result is one of:

- `CONTINUE`: enter the transaction and puzzle stages.
- `SKIP`: handle a business blocker and write one terminal skip row.
- `RESTART_AFTER_UPDATE`: return to the dashboard and submit the same NIK once
  more. This is not a technical retry and creates no extra terminal row.

### Happy flows

All rows below end in exactly one `completed` terminal row after the puzzle is
solved and the dashboard is restored.

| Flow after NIK check | TaskBot action |
| --- | --- |
| `transaction -> puzzle` | Continue directly to `CEK PESANAN`, sale submission, and puzzle. |
| `choose type -> transaction -> puzzle` | Prefer `Rumah Tangga`, then `Usaha Mikro`, then the first usable radio; click `LANJUTKAN` once. |
| `consent -> transaction -> puzzle` | Click consent `SELANJUTNYA` once, then resolve the current state again. |
| `choose type -> consent -> transaction -> puzzle` | Perform both optional one-shot actions, then transact. |
| `NIB reminder -> transaction -> puzzle` | For the Usaha Mikro NIB-specific message, click `NANTI SAJA, LANJUT PENJUALAN/TRANSAKSI` once. This is not the customer-data-update modal. |
| `choose type and/or consent -> NIB reminder -> transaction -> puzzle` | Handle every visible optional state once, in the order presented by the application. |
| `update data -> SAME NIK -> transaction -> puzzle` | Open, populate, submit, confirm, return home, then restart the same NIK once. |
| `choose type -> update data -> SAME NIK -> transaction -> puzzle` | Select the customer type before running the update chain. |
| `consent -> update data -> SAME NIK -> transaction -> puzzle` | Continue consent before running the update chain. |
| `choose type -> consent -> update data -> SAME NIK -> transaction -> puzzle` | Run the complete onboarding and update chain, then transact on the same NIK. |

The application may insert consent or the NIB reminder between other optional
states. TaskBot re-evaluates the live page after every click, so those variants
use the same state handlers rather than separate hard-coded flows.

The automatic update chain is strictly gated:

```text
update required
-> update form
-> confirmation
-> update success
-> dashboard
-> paced SAME NIK restart
-> transaction
```

`nik_parser.py` must successfully prepare the city/regency and birth-date data
before the form is mutated. Opening the form, submitting it, confirming it, and
restarting the same NIK use the shared update pacer. Submit must lead to the
confirmation state, confirmation must lead to success, and each mutation button
is clicked at most once.

Before `LANJUTKAN PENJUALAN`, TaskBot presses `Escape` on the NIK combobox to
dismiss its autocomplete portal. It then uses a normal Playwright click; it does
not force-click through a genuine blocker dialog.

### Unhappy business flows

These are expected application decisions. They do not use the general-error
retry path. Unless stated otherwise, TaskBot closes the visible dialog when
needed, resets the customer entry, records one skip, applies the post-skip
cooldown, and proceeds to the next NIK.

| Trigger or exact application state | Handling | Terminal status / effect |
| --- | --- | --- |
| `NIK belum 17 tahun` | Clear/reset the NIK entry. | `skipped_nik is not yet 17 years old` |
| Customer is not registered | Click the modal close action once and reset. | `skipped_not_registered` |
| Title `Tidak Dapat Melanjutkan Pendaftaran Pelanggan` **and** message `Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan ini. Silakan coba lagi di hari berikutnya.` | Click the visible modal-scoped `Tutup` once. It is terminal whether it appears immediately after NIK submission or during an update action. Never resubmit that NIK that day. | `skipped_registration_request_limited`; DB status `429`, quota delta `0` |
| `NIK pelanggan yang didaftarkan tidak valid.` | Click `Tutup` once and reset. | `skipped_The registered customer's NIK is invalid` |
| `Pelanggan Tidak Dapat Transaksi di Pangkalan Ini` | Click `Tutup` once and reset. | `skipped_Customers Cannot Transact at This Base` |
| NIK is flagged for an unusual transaction at another base, unusual distance, and close time | Click `Tutup` once and reset. | `skipped_The customer's NIK indicates an unusual transaction at another base with an unusual distance and close time.` |
| `Tidak dapat transaksi karena telah melebihi batas kewajaran pembelian LPG 3 kg bulan ini.` before or after `CEK PESANAN` | Preserve the exact warning in the reason and try `GANTI PELANGGAN`. | `skipped_max_kuota` |
| Sellable stock becomes empty on the transaction page | Record the stage and exact alert text. | `skipped_out_of_stock`; stop only the affected account |
| Stock appears empty while opening `Catat Penjualan` | Confirm it up to three times, refreshing the dashboard before the final check. | If still empty: `skipped_out_of_stock`; stop only the affected account |
| Puzzle solve fails and the exact `Cocokan Gambar untuk Proses Keamanan Penjualan` modal requests another challenge | Refresh and retry, up to five total puzzle attempts. | If exhausted: `failed_puzzle_solve`, then recover the dashboard/session |
| Slider reports failure but the exact failed-puzzle modal is absent | Do not blindly move or retry the slider against an unknown page. | `failed_puzzle_solve` after the current attempt |

The daily registration-limit locator requires the exact title and message on the
same visible Mantine modal. It intentionally supports the live dialog even when
an ancestor is marked `aria-hidden="true"`; generated CSS classes and absolute
XPath indexes are not used.

The NIB reminder is a happy, continuable flow. It is kept separate from
`Data Pelanggan belum lengkap`; the automatic update workflow never silently
falls back to the NIB reminder's `NANTI SAJA` action.

### Update failure flows

Customer-update failures are terminal for the current NIK because replaying a
mutation can duplicate a registration request.

| Failure | Behavior |
| --- | --- |
| NIK parsing/mapping fails before form population | Do not fill or submit the form; write one `error` row, capture a failure artifact, and recover. |
| Update form does not appear after `Update Data Pelanggan` | Write one `error` row; do not reopen it through a general retry. |
| Confirmation does not appear after submit | Keep the submit one-shot; write one `error` row and recover. |
| Confirmation is visible without a submission owned by this workflow | Refuse to confirm it and write one `error` row. |
| Success does not appear after confirmation, or success appears without an owned confirmation | Do not continue to a transaction; write one `error` row. |
| Dashboard cannot be restored after success | Write one `error` row and recover. |
| The same NIK asks for `UPDATE_REQUIRED` or `UPDATE_FORM` again after its one allowed successful update/restart | Raise the update-loop guard and write one `error` row; never perform a second update. |
| Registration-request-limit modal interrupts an update click or its transition wait | The blocker overrides the update error: click `Tutup` once and record `skipped_registration_request_limited`. |

### Recoverable anomaly flows

Technical retries are appended to `retries.jsonl`; they never add a second
terminal transaction row.

| Anomaly | Recovery and bound |
| --- | --- |
| Session expires before NIK work, during a precheck action, or during an update action | Give session expiry highest priority, recover/login, and retry the same NIK once. If it expires again, write one terminal `error` row. |
| Transient Playwright, browser, network, unknown-state, or other general error | Recover the session/dashboard and retry the same NIK up to two times. On exhaustion, write one terminal `error` row. |
| Old consent, customer-type, NIB, form, or confirmation DOM remains visible during a transition | Poll for a different known state within the bounded transition timeout; do not click the old action again. |
| A business blocker disappears between detection and its exact read | Resolve the current state again. Do not silently skip the NIK without a terminal report. |
| NIK autocomplete covers `LANJUTKAN PENJUALAN` | Dismiss it with `Escape`, retain the NIK value, and click normally. This prevention does not consume a retry. |
| Registration-limit modal appears between state resolution and an action click | Re-probe the blocker from the action error, close it once, and terminate as a business skip instead of retrying the NIK. |
| Customer-update actions from multiple operator threads would overlap | The application-wide lock reserves paced action slots. Update pacing does not add, clear, or consume skip-pressure entries. |
| Eight terminal skips occur within 48 seconds | The independent skip-pressure limiter waits at least the remaining 48-second window, plus up to five seconds of jitter, then starts a fresh skip window. |
| PostgreSQL commit fails for a terminal NIK | The local CSV/JSONL row is already flushed and fsynced. Keep the DB row pending, retry it during final flush, and mark the account unsuccessful if persistence still fails. |
| DB sync is disabled | Keep all local terminal and workflow reports; emit a DB-sync-skipped event. |
| One operator/browser/account fails | Finish and report that account independently; other operator threads continue. |

### Flow invariants

- Each processed NIK has at most one terminal row: `completed`, `skipped_*`,
  `failed_puzzle_solve`, or `error`.
- Consent, update milestones, same-NIK restart, and technical retries are events,
  not additional transaction rows.
- Same-NIK update restart consumes no general retry, session retry, or skip-rate
  quota. It is paced by the separate update limiter.
- A business skip never enters the puzzle or general-retry path.
- A successful transaction calls `record_success()`; customer update success
  alone is not a completed sale and does not clear skip pressure.
- The resolver uses semantic text, roles, and visible scoped DOM. It does not
  depend on generated Mantine hashes or absolute XPath indexes.

## NIK-derived customer data

`nik_parser.py` is the single NIK decoder. It reads `nik_region_mapping.json` from the project root and validates province, regency/city, district, encoded birth date, and gender.

The current update rule is isolated in `customer_update_data_from_nik()`:

```text
original_nik        -> browser NIK
kota_kabupaten     -> city / birth-place field
birth_date.day     -> Tgl
birth_date.month   -> Indonesian Bln name
birth_date.year    -> Thn
```

Page objects receive validated `CustomerUpdateData` and never parse NIKs.

## Install

Requirements: Python 3.14+, [uv](https://docs.astral.sh/uv/), and a supported Playwright browser. PostgreSQL is optional.

```powershell
uv sync
uv run playwright install
Copy-Item .env.example .env
```

On macOS/Linux, use `cp .env.example .env` for the last command.

## Configuration

```env
URL_APPLICATION=https://your-app.example
HEADLESS=True
MASK=0
TASKBOT_INTERACTION_DEBUG=0
TASKBOT_INTERACTION_PAUSE=0

EMAIL_1=first.operator@example.com
PIN_1=123456
NIK_1=3573051108720003,3573021802810011
OPERATOR_1_ID=operator_01

EMAIL_2=second.operator@example.com
PIN_2=654321
NIK_2=3573051108720003
OPERATOR_2_ID=operator_02

CUSTOMER_UPDATE_MIN_INTERVAL_SECONDS=1.0
CUSTOMER_UPDATE_JITTER_SECONDS=0.25
```

`EMAIL`, `PIN`, `NIK`, and `OPERATOR_ID` remain available for one backward-compatible account. Numbered accounts are sorted numerically and run concurrently. If an explicit `OPERATOR_n_ID` is omitted, the intrinsic numeric suffix becomes `operator_01`, `operator_02`, and so on. IDs must be unique and cannot be an email, PIN, NIK, or path-like value.

The update interval and jitter are non-negative seconds. They pace only customer-update mutations and the same-NIK restart. The existing skipped-NIK circuit breaker remains separate.

### Browser and privacy modes

`HEADLESS=True` or `1` hides the browser; `False` or `0` shows it.

Interaction diagnostics are controlled from `.env`:

- `TASKBOT_INTERACTION_DEBUG=1` enables traces, screenshots, DOM/state logs,
  and network timing; `0` disables them.
- `TASKBOT_INTERACTION_PAUSE=1` opens Playwright Inspector at diagnostic
  checkpoints; `0` disables pauses. Pauses require both
  `TASKBOT_INTERACTION_DEBUG=1` and `HEADLESS=0`.

Both settings default to disabled. `main.py` loads `.env` before the browser
session starts, so no PowerShell environment-variable setup is needed.

`MASK` accepts case-insensitive values:

- Masked: `1`, `true`, `on`, `yes`.
- Unmasked: `0`, `false`, `off`, `no`.

If absent, `MASK` defaults to enabled. `3573051108720003` becomes `357305****720003` in logs, report files, summaries, workflow events, and puzzle artifact names. `MASK=0` permits valid NIKs in full for development.

Email, PIN, passwords, tokens, cookies in logs, and registered runtime secrets remain redacted regardless of `MASK`. `operator_id` is non-secret and always visible. Report directories use that stable ID directly and never use raw, masked, or hashed email identity.

### Logging

```env
LOG_LEVEL=INFO
LOG_FILE_LEVEL=DEBUG
LOG_ROTATION=25 MB
LOG_RETENTION=30 days
LOG_COMPRESSION=gz
```

One `run_id` is created before account fan-out. Logs and all operator reports use the same root:

```text
reports/<yyyy>/<mm>/<dd>/<run_id>/application.log
reports/<yyyy>/<mm>/<dd>/<run_id>/application.jsonl
reports/<yyyy>/<mm>/<dd>/<run_id>/database/database_events.jsonl
```

The default directory is anchored to the project root even when TaskBot is launched from another working directory. Browser automation and customer/transaction events go to `application.log` and `application.jsonl`; `database_events.jsonl` intentionally contains only database activity and can remain empty when DB sync is disabled. Every structured event carries `run_id`; operator-scoped work also carries `operator_id`. Console output is immediate, queued file records are drained at shutdown, and `.env` logging settings are loaded before logging is configured.

Business milestones use INFO, locator diagnostics DEBUG, recoverable conditions WARNING, and terminal update failures ERROR. Structured `transaction.stage.*` events trace NIK submission, customer-state resolution, order check, sale submission, puzzle outcome, and completion. The exact monthly-limit warning is preserved in the terminal skip reason.

### PostgreSQL

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=taskbot
DB_USER=taskbot
DB_PASSWORD=change-me
NAME_OPERATORS_1=First Operator
NAME_OPERATORS_2=Second Operator
OPERATOR_1_ID=operator_01
OPERATOR_2_ID=operator_02
```

```powershell
uv run python -m scripts.db_management init
uv run python -m scripts.db_management sync-report <path-to-items.jsonl>
```

File-based manual sync needs an unmasked report produced with `MASK=0`; a masked NIK cannot be reconstructed. Use `--table OPERATOR_1` (or the matching numbered table) when an imported legacy report has no resolvable operator. Only configured numbered targets are required, so a one-account setup does not need `NAME_OPERATORS_2`; arbitrary numeric suffixes such as operator 3 are supported.

At runtime, every terminal `TransactionRow` is appended and fsynced locally, then submitted as a one-row DB transaction through the account's persistent connection. A skipped or unresolved DB row is treated as a sync failure rather than acknowledged. The pending row remains available for final retry and the account is marked unsuccessful if persistence still fails. Consent, update, restart, workflow, and retry events never enter the transaction table.

## Run

```powershell
uv run main.py
```

Each account owns its reporter, limiter, browser, processor, and persistent DB connection. One account failure does not stop other account threads.

## Reports

```text
reports/<yyyy>/<mm>/<dd>/<run_id>/
  run_meta.json
  application.log
  application.jsonl
  database/
    database_events.jsonl
  operators/
    operator_01/
      items.csv
      items.jsonl
      workflow_events.jsonl
      retries.jsonl
      summary.json
      analytics.json
      items_snapshot.json
    operator_02/
      ...
  artifacts/
    screenshots/<operator_id>/
    traces/<operator_id>/
```

- `items.csv` and `items.jsonl`: append-only terminal outcomes.
- `workflow_events.jsonl`: immediately appended business milestones such as consent, update, confirmation, success, restart, and failure.
- `retries.jsonl`: immediately appended technical retry history; retries never create terminal rows.
- `items_snapshot.json`: terminal rows, mappings, retries, puzzle statistics, analytics, and compact `workflow_summary`.
- `analytics.json`: status, performance, puzzle, skip, and error aggregates with `run_id` and `operator_id`.
- `summary.json`: compact current-run operator totals and file paths; detailed retry history stays in JSONL.
- Top-level `run_meta.json`: credential-free execution status and operator aggregation.

The full workflow chronology is not duplicated into summaries. Its compact summary includes event count, consent/update NIK counts, successes, restarts, failures, and repeated requests. `RetryEvent` remains technical retry telemetry; `WorkflowEvent` is business progression. A successful consent/update/restart/transaction path still produces exactly one terminal `completed` row.

Puzzle images and customer-update failure screenshots are stored under the shared run and stable operator ID. NIKs follow `MASK`; masked Windows filenames use `xxxx` as the filesystem-safe replacement for the four hidden digits. Slider `meta.json` includes the run ID, operator ID, and rendered NIK.

## Architecture

```text
main.py -> shared RunContext + CustomerUpdateRateLimiter
        -> AccountRunner -> BrowserSession -> TransactionProcessor
                                      |-> TransactionPrechecksService
                                      |   |-> consent/update page objects
                                      |   `-> NIK parser + data adapter
                                      |-> Penjualan / CekPenjualan
                                      |-> PuzzleService
                                      `-> SessionRecoveryService
         `-> TransactionReporter -> terminal files + one-row DB callback
                                |-> workflow_events.jsonl
                                `-> retries.jsonl
```

Focused page objects live in `src/infrastructure/browser/page_objects/`. The precheck service owns orchestration; the dashboard object does not own the whole update workflow.

## Development

```powershell
$env:PYTHONPATH='.'
uv run pytest -q
uvx ruff format .
uvx ruff check .
```

Tests cover direct transaction, customer type, consent, automatic update mapping, same-NIK restart, NIK autocomplete dismissal, bounded repeated updates, shared update pacing, the daily registration-request terminal modal at update boundaries, retry isolation, masking, credential redaction, shared run/operator identity, workflow telemetry, one-row reporting, stock/quota blockers, puzzle artifacts, session recovery, multi-account execution, and per-terminal-NIK DB synchronization.

The semantic selectors for `Pernyataan Persetujuan`, `Update Data Pelanggan`, `btnSubmitUpdate`, `YA, Perbarui DATA PELANGGAN`, and `KEMBALI KE HALAMAN UTAMA` require live verification whenever the deployed UI changes.
