# Operator 2 quick guide

The [first section of the README](../README.md#find-an-operators-input-result-and-quota) now uses one operator for all three questions. It points to the customer list, the sale result and the customer's two quota counts.

## How to check

From the project root, run the following PowerShell command. It returns the operator 2 setting on line 9, the report path on line 13, the sale result on line 14 and the table on line 16.

```powershell
uv run --locked rg -n -m 4 "NIK_2|operators/operator_02/items.jsonl|If .status. is .completed.|In pgAdmin" README.md
```

## F119 · VERIFIED · One operator in all three examples

The owner reported reading the opening section three to six times to understand it. The README at `beb593e` mixed operators 1 and 2 and put the input parsing and quota update rules in the opening list. The revised section uses operator 2 throughout. It splits the report lookup into two steps and gives each quota column its own bullet. [Read the revised points](../README.md#find-an-operators-input-result-and-quota)

The example follows `NIK_{suffix}` for the input, `operator_{int(suffix):02d}` for the default report folder and `OPERATOR_{suffix}` for the table. The reporter sets `self.jsonl_path = self.run_dir / "items.jsonl"`. The quota SQL keeps the current count and the recorded maximum. [Input and default folder ID](../src/infrastructure/config/settings.py#L119) · [Report file](../src/web/reporter.py#L956) · [Table name](../src/infrastructure/database/operator_store.py#L184) · [Quota columns](../src/infrastructure/database/_operator_sql.py#L93)

The baseline was `beb593e` with Ruff 0.17.6, mypy 2.4.1 and pytest 9.0.2. The clean documentation snapshot passed `uv run --locked pytest` (`1450 passed in 50.32s`). The golden comparison was **NOT RUN** because the change only affects Markdown.

## F125 · VERIFIED · The owner accepted the revised guide

On 2026-11-25 the owner answered the reader check with “yes. the guide is clear for me now.” This closes the open readability check for Phase 5. The accepted guide uses operator 2 for the configured input, per-customer result and quota lookup. [README example](../README.md#find-an-operators-input-result-and-quota) · [Phase 5 technical evidence](2026-11-24-phase-5-reader-guide.md#f118--verified--local-acceptance)

## Open items

The reader check is complete. Future work has its own [database questions](2026-11-25-database-plan.md#questions-and-answers) and [project structure questions](2026-11-25-project-structure-plan.md#questions-and-answers).
