# TaskBot glossary

- **What this is.** The plain meaning of every shop, owner and TaskBot term a reader meets in the code, the reports and the database. Each entry links to where today’s code uses it.
- **Who it is for.** A developer or agent who is new to TaskBot. The [where to look guide](where-to-look.md) uses these terms.
- **Shop texts stay in Indonesian.** The shop shows Indonesian text, and the code matches that text exactly. The English meaning is for reading only. Structure Q2 decided that module names become English later, with the Indonesian page title kept in the docstring and in this glossary ([owner answer](../plans/2026-11-26-plan-owner-questions-and-answers.md#project-structure-plan-questions)).
- **Where it will live.** Here, in `docs/guides/`, until Phase R2 creates `src/shared/`. Its README will then link to this file ([phase table](../plans/2026-11-25-plan-project-structure.md#phases-proof-and-rollback)).
- **Status.** Written in Phase R0 on 2026-11-26 at revision `6a7a97b`. Line links point at that revision. [Activity doc](../activities/2026-11-26-structure-r0-glossary-and-code-map.md)

## Shop and business terms

| Term | Plain meaning | Where today’s code uses it |
| --- | --- | --- |
| NIK | *Nomor Induk Kependudukan*, the 16-digit Indonesian national identity number. In TaskBot it is the customer number. User-facing text says “customer number” (Modernization Q8). Machine names such as `nik` stay until a separate migration. | [`_NIK_PATTERN`](../../nik_parser.py#L14) · [`normalise_nik`](../../nik_parser.py#L45) |
| Operator | One shop account (`EMAIL_n`, `PIN_n`) that sells to its own customer list (`NIK_n`). Its stable ID, such as `operator_01`, names its report folder and its database table. | [`EMAIL_{suffix}`](../../src/infrastructure/config/settings.py#L120) · [`NIK_{suffix}`](../../src/infrastructure/config/settings.py#L122) |
| Pangkalan | The base: the LPG outlet that the operator account belongs to. | [`_CANNOT_TRANSACT_AT_BASE_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L57) |
| LPG 3 kg, tabung | The subsidised 3 kg gas cylinder that is sold. *Tabung* means cylinder. The dashboard stock reads “Tabung”. | [`Tabung`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L143) · [`_MAX_KUOTA_ALERT_PATTERN`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L20) |
| Kuota | Quota: how many confirmed sales this customer had this month. The shop decides the monthly limit and reports it with the maximum-quota warning (Database Q18). | [`next_kuota`](../../src/infrastructure/database/_operator_sql.py#L93) |
| Max kuota | The maximum-quota case: the shop refuses a sale because the customer reached this month’s limit. TaskBot records `skipped_max_kuota`. | [`skipped_max_kuota`](../../src/infrastructure/database/operator_store.py#L63) · [`check_max_kuota`](../../src/application/services/transaction_prechecks.py#L1052) |
| Rumah Tangga, Usaha Mikro | Customer types: household and micro business. TaskBot prefers Rumah Tangga, then Usaha Mikro, then the first usable option. | [`Rumah Tangga`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L1127) |
| NIB | *Nomor Induk Berusaha*, the business registration number. A Usaha Mikro customer may see a “complete your NIB” reminder, which TaskBot continues past once. | [`_NIB_REMINDER_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L41) |
| Kota/kabupaten, Tgl, Bln, Thn | City or regency, and the day, month and year fields of the customer-update form. TaskBot fills them from the NIK. The month is written as an Indonesian month name. | [`kota_kabupaten`](../../nik_parser.py#L39) · [`indonesian_month_name`](../../src/application/models/customer_workflow.py#L80) |
| Lowokwaru | The owner’s home district. A customer belongs to it when the NIK starts with the district’s six-digit region prefix, wherever the customer lives. It is the default customer source, and “outside Lowokwaru” is the second option (Database Q2). Not in the Python code today. | [Database plan rule](../plans/2026-11-25-plan-database-customer-selection.md#rules-agreed-with-the-owner) · [Owner answer](../plans/2026-11-26-plan-owner-questions-and-answers.md#database-plan-questions) |
| WIB | *Waktu Indonesia Barat*, the Asia/Jakarta time zone (UTC+7). The owner chose it as the clock that decides “today” and “this month” (Database Q9). Today’s code writes the operator machine’s local time without a time zone. | [Owner answer](../plans/2026-11-26-plan-owner-questions-and-answers.md#database-plan-questions) |
| Rekap Penjualan | The shop’s sales recap page. The owner checks it to verify a sale when TaskBot’s result is uncertain (Modernization Q10). TaskBot never opens it. | [Owner answer](../plans/2026-11-26-plan-owner-questions-and-answers.md#modernization-plan-questions) |

## Database columns

Each operator has one table, `OPERATOR_1`, `OPERATOR_2` and so on. All of them have the same columns, in this order. [`COLUMN_NAMES`](../../src/infrastructure/database/_operator_sql.py#L9)

| Column | Plain meaning | Where it is set |
| --- | --- | --- |
| `OPERATOR` | The operator’s display name. | [`from_report_payload`](../../src/infrastructure/database/operator_store.py#L279) |
| `NIK` | The customer number, stored as an integer. | [`_parse_nik`](../../src/infrastructure/database/operator_store.py#L1233) |
| `NAMA_KONSUMER` | Customer name (*konsumer* means consumer). | [`nama_konsumer`](../../src/infrastructure/database/operator_store.py#L269) |
| `JENIS_PENGGUNA` | Customer type (*jenis pengguna* means user type), for example Rumah Tangga. | [`jenis_pengguna`](../../src/infrastructure/database/operator_store.py#L276) |
| `KUOTA` | Confirmed sales this month. A confirmed sale adds 1, anything else adds 0. | [`kuota_delta=1 if is_successful else 0`](../../src/infrastructure/database/operator_store.py#L300) |
| `MAX_KUOTA` | The highest `KUOTA` this customer ever reached, kept across months (Database Q18). | [`next_max_kuota`](../../src/infrastructure/database/_operator_sql.py#L108) |
| `STATUS_CODE`, `STATUS_CODE_DESCRIPTION` | An HTTP-style code and text for the last result, for example `200` “Transaction successful” or `409` “Max kuota reached”. | [`_STATUS_MAPPINGS`](../../src/infrastructure/database/operator_store.py#L59) |
| `PROBLEM`, `CONFLICT` | The reason for a result that is not a sale, and a flag that is true when there is one. | [`_build_problem`](../../src/infrastructure/database/operator_store.py#L1209) |
| `LAST_TRANSACTION_TIME`, `PREVIOUS_TRANSACTION_TIME` | The last two confirmed-sale times. | [`last_transaction_time`](../../src/infrastructure/database/operator_store.py#L868) |
| `UPDATED_TIME`, `CREATED_TIME` | When the row last changed and when it was first written. | [`updated_time`](../../src/infrastructure/database/_operator_sql.py#L90) |

## Shop page texts

The exact Indonesian text the code looks for, with its meaning. Matching ignores case where the code uses a pattern.

| Shop text | English meaning | What TaskBot does | Where |
| --- | --- | --- | --- |
| Catat Penjualan | Record a sale | Dashboard tile that opens the sale page. | [`Catat Penjualan`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L146) |
| LANJUTKAN PENJUALAN | Continue the sale | Button after the customer number and customer type. | [`LANJUTKAN`](../../src/infrastructure/browser/page_objects/customer_type_modal.py#L323) |
| Pernyataan Persetujuan | Statement of consent | Optional consent page. TaskBot clicks SELANJUTNYA (“next”) once. | [`Pernyataan`](../../src/infrastructure/browser/page_objects/consent_page.py#L11) · [`SELANJUTNYA`](../../src/infrastructure/browser/page_objects/consent_page.py#L28) |
| Segera Lengkapi NIB | Complete your NIB soon | NIB reminder. TaskBot clicks “Nanti saja, lanjut penjualan” (“later, continue the sale”) once. | [`_NIB_CONTINUE_LATER_BUTTON`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L45) |
| Data Pelanggan belum lengkap | Customer data is incomplete | Starts the one allowed customer update. The button is “Update Data Pelanggan”. | [`Data`](../../src/infrastructure/browser/page_objects/update_required_modal.py#L12) · [`Update`](../../src/infrastructure/browser/page_objects/update_required_modal.py#L13) |
| YA, Perbarui DATA PELANGGAN | Yes, update the customer data | Confirms the update form. | [`YA, Perbarui DATA PELANGGAN`](../../src/infrastructure/browser/page_objects/update_confirmation_modal.py#L18) |
| Data Pelanggan berhasil … | Customer data updated | Update success. TaskBot returns home and restarts the same customer once. | [`berhasil`](../../src/infrastructure/browser/page_objects/update_success_modal.py#L11) |
| Informasi Pelanggan | Customer information | Section on the sale page where TaskBot reads the name and type. | [`Informasi`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L40) |
| CEK PESANAN | Check the order | Sale page button before the sale is submitted. | [`CEK PESANAN`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L58) |
| Ganti Pelanggan | Change customer | Leaves the sale page after a maximum-quota warning. | [`Ganti Pelanggan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L73) |
| PROSES PENJUALAN | Process the sale | Submits the sale. | [`PROSES PENJUALAN`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L31) |
| Cocokan Gambar untuk Proses Keamanan Penjualan | Match the picture for sales security | The puzzle. Shown again when a solve failed. | [`_FAILED_PUZZLE_MODAL_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L60) |
| KEMBALI KE HALAMAN UTAMA | Back to the main page | After a sale, this button is TaskBot’s only evidence that the sale went through. | [`KEMBALI KE HALAMAN UTAMA`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L87) |
| Tidak dapat transaksi karena telah melebihi batas kewajaran pembelian LPG 3 kg bulan ini | No sale: this month’s reasonable LPG 3 kg purchase limit is exceeded | Maximum quota. Recorded as `skipped_max_kuota`. | [`_MAX_KUOTA_ALERT_PATTERN`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L20) |
| Stok Tabung Kosong | Cylinder stock is empty | Out of stock. Recorded as `skipped_out_of_stock` and stops this operator for the day. | [`Stok Tabung Kosong`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L47) |
| NIK belum 17 tahun | The person is not yet 17 | Skip. | [`_NIK_UNDER_17_VALIDATION_TEXT`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L53) |
| Pelanggan Tidak Terdaftar | Customer not registered | Skip. | [`Pelanggan Tidak Terdaftar`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L254) |
| NIK pelanggan yang didaftarkan tidak valid. | The registered customer number is invalid | Skip. | [`_INVALID_REGISTERED_NIK_MESSAGE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L56) |
| Tidak Dapat Melakukan Transaksi | Cannot make a transaction | Skip, then recover the session. | [`_CANNOT_TRANSACT_MODAL_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L54) |
| NIK pelanggan diblokir karena pelanggan terindikasi fraud | Customer number blocked for suspected fraud | Skip, then recover the session. | [`_FRAUD_MODAL_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L55) |
| Pelanggan Tidak Dapat Transaksi di Pangkalan Ini | The customer cannot buy at this base | Skip. | [`_CANNOT_TRANSACT_AT_BASE_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L57) |
| Tidak Dapat Melanjutkan Transaksi | Cannot continue the transaction | Unusual purchase at another base. Skip. | [`_UNUSUAL_TRANSACTION_MODAL_TITLE`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L58) |
| Tidak Dapat Melanjutkan Pendaftaran Pelanggan | Cannot continue the customer registration | Too many registration requests today. TaskBot clicks Tutup (“close”) once and records `skipped_registration_request_limited`. | [`_REGISTRATION_REQUEST_LIMITED_MODAL_TITLE_TEXT`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L61) |

## Indonesian words in today’s code names

Today many classes and methods carry Indonesian words. Structure Q2 renames modules to English in the move phases. Until then, this list decodes them.

| Word | Meaning | Example in the code |
| --- | --- | --- |
| *penjualan* | sale | [`Penjualan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L55) is the sale page. |
| *cek* | check | [`CekPenjualan`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L27) is the sale check page. |
| *catat* | record | [`catat_penjualan`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L740) opens the sale page for one customer. |
| *pesanan* | order | [`cek_pesanan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L93) clicks CEK PESANAN. |
| *proses* | process | [`proses_penjualan`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L94) submits the sale. |
| *kembali* | back | [`kembali_ke_dashboard`](../../src/infrastructure/browser/page_objects/cek_penjualan_page.py#L102) returns to the dashboard. |
| *ganti* | change | [`ganti_pelanggan`](../../src/infrastructure/browser/page_objects/penjualan_page.py#L213) leaves the current customer. |
| *pelanggan* | customer | [`select_jenis_pelanggan`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L1090) selects the customer type. |
| *jenis* | type | `jenis_pelanggan` (customer type), `jenis_pengguna` (user type), `jenis_kelamin` (sex). |
| *nama*, *pengguna*, *konsumer* | name, user, consumer | [`nama_pengguna`](../../src/infrastructure/reporting/models.py#L41) is the customer name in a report row. |
| *perbarui data* | update data | [`detect_perbarui_data_pelanggan_if_needed`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L1552) detects the update request. |
| *tidak terdaftar* | not registered | [`read_pelanggan_tidak_terdaftar_reason_if_present`](../../src/infrastructure/browser/page_objects/dashboard_page.py#L1380) |
| *provinsi*, *kecamatan* | province, district | [`NIKResult`](../../nik_parser.py#L36) holds the fields decoded from a NIK. |

## TaskBot terms

| Term | Plain meaning | Where |
| --- | --- | --- |
| Run, `run_id`, run folder | One start of `main.py`. All operators of that start share one `run_id` and write under `reports/<yyyy>/<mm>/<dd>/<run_id>/`. | [`RunContext`](../../src/application/dto/run_context.py#L56) · [`build_timestamped_run_dir`](../../src/path_utils.py#L15) |
| Precheck | What TaskBot checks after it enters a customer number and before the sale: customer type, consent, NIB reminder, update and blockers. | [`handle_pre_checks`](../../src/application/services/transaction_prechecks.py#L137) |
| Customer state | What the page shows right now, for example `CONSENT` or `TRANSACTION_READY`. | [`CustomerState`](../../src/application/models/customer_workflow.py#L17) |
| Precheck action | The decision a precheck returns: `CONTINUE`, `SKIP`, `SKIP_REQUIRES_RECOVERY` or `RESTART_AFTER_UPDATE`. | [`PrecheckAction`](../../src/application/models/customer_workflow.py#L10) |
| Terminal row | The one final result line for one customer in one run: `completed`, `skipped_*`, `failed_puzzle_solve` or `error`. Workflow and retry events are not terminal rows. | [`_record_row`](../../src/web/reporter.py#L1134) |
| Confirmed sale | A sale with positive evidence on the page. Only a confirmed sale becomes `completed` and adds 1 to `KUOTA`. | [`success_confirmed`](../../src/application/models/transaction_outcome.py#L18) |
| Skip | A business refusal by the shop. It never enters the puzzle or the general retry. | [`_record_skip_and_cooldown`](../../src/application/services/transaction_prechecks.py#L1151) |
| Skip pressure | The skip rate limiter. `main.py` sets it to 8 skips in 48 seconds, after which TaskBot waits before the next customer. The class defaults (5 in 60) are not used by the app. | [`SkipRateLimiter`](../../src/web/rate_limiter.py#L155) · [`max_skips=8`](../../main.py#L42) |
| Quota journal, delivery receipt | A local file that keeps a confirmed sale until the database has it, and a database record that a delivery was applied once. Used by the recovery command. | [`QuotaJournal`](../../src/infrastructure/database/quota_journal.py#L33) · [`ensure_delivery_receipts`](../../src/infrastructure/database/operator_store.py#L550) |
| Masking (`MASK`) | Hides the middle digits of a customer number in logs, reports and file names. On by default. | [`display_nik`](../../src/privacy.py#L39) |
| Golden master | The recorded output of a dummy-shop run (reports and database rows), compared byte for byte after a change. It is the proof that behavior did not change. | [Phase 1 acceptance procedure](../plans/2026-11-23-plan-modernization.md#phase-1-acceptance-procedure) |
| Dummy shop | The local fake shop that tests and the golden master run against. Never the real site. | [Phase 1 notes](../activities/2026-11-23-phase-1-behavior-baseline.md#9-whole-app-test-in-the-local-dummy-shop) |
