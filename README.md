# TaskBot 🤖

**Reclaiming time by automating the mundane.**

TaskBot is a Python automation tool designed to handle repetitive manual tasks in specific web applications. It navigates, logs in, and executes workflows so you don't have to.

## 🚀 The Evolution: Migrating to `uv`

To ensure stability and lightning-fast performance, TaskBot has migrated from the traditional `pip` workflow to **[uv](https://docs.astral.sh/uv/)**.

**Why the change?**
As Python evolves (hello, Python 3.14!), managing dependencies manually can become a headache. We encountered issues where older packages (like NumPy) conflicted with newer Python versions.

By switching to `uv`, we now have:

* **Automatic Version Resolution:** `uv` automatically finds the correct package versions for your machine.
* **Reproducibility:** A `uv.lock` file ensures that the code works on your machine exactly as it does on ours.
* **Speed:** Dependency installation is now 10–100x faster.

---

## 🛠️ Getting Started

Follow these steps to get the bot up and running in minutes.

### 1. Install `uv`

If you haven't already, install the tool.

* **Windows (PowerShell):**

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

* **MacOS/Linux:**

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

### 2. Set Up the Project

You don't need to manually create virtual environments or install Python versions anymore. `uv` handles it all.

```bash
# 1. Sync dependencies (creates the virtual env automatically)
uv sync

# 2. Install Playwright browsers (required for web automation)
uv run playwright install

# 3. Configuration
cp .env.example .env
# Then, edit the .env file with your credentials
```

For concurrent execution, define multiple accounts in `.env`:

```env
EMAIL_1=first.operator@example.com
PIN_1=123456
NIK_1=1234567890123456,2345678901234567

EMAIL_2=second.operator@example.com
PIN_2=654321
NIK_2=3456789012345678,4567890123456789
```

Single-account keys (`EMAIL`, `PIN`, `NIK`) are still supported.

### 3. Run the Bot

Forget about venv\Scripts\activate. With uv, you simply "run" the command, and it handles the environment in the background.

To execute the main script:

```bash
uv run main.py
```

If multiple numbered accounts are configured, the bot runs each account in its own thread with an isolated browser process.

## Structured JSON Logging

Runtime and report logs are emitted with **Loguru** to:

* `reports/logs/<yyyy>/<mm>/<dd>/<hhmmss>/taskbot_<run_id>.jsonl` (structured JSON lines for indexing/search/analytics)
* `reports/<operator>/<yyyy>/<mm>/<dd>/<hhmmss>/` (per-operator run reports: CSV, JSONL, analytics, snapshots)
* Console output (human-readable stream)

Optional `.env` controls:

```env
HEADLESS=True # TRUE/True/1 for headless, FALSE/False/0 to show the browser
LOG_LEVEL=INFO
LOG_FILE_LEVEL=DEBUG
LOG_ROTATION=25 MB
LOG_RETENTION=30 days
LOG_COMPRESSION=gz
```

## Database Management

Set the PostgreSQL and operator mapping values in `.env`:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=taskbot
DB_USER=taskbot
DB_PASSWORD=change-me
NAME_OPERATORS_1=First Operator
NAME_OPERATORS_2=Second Operator
```

Each operator syncs terminal transaction rows independently in batches of 100;
the final partial batch is flushed when that operator's run finishes.

Create the configured database if needed and ensure `OPERATOR_1` and `OPERATOR_2`
exist:

```bash
uv run python -m scripts.db_management init
```

When the bot finishes an operator session, it automatically syncs that run's
`items.jsonl` report into the matching operator table when the DB environment
variables above are configured. The manual sync command is still available:

```bash
uv run python -m scripts.db_management sync-report reports/<operator>/<yyyy>/<mm>/<dd>/<hhmmss>/items.jsonl
```

Use `--table OPERATOR_1` or `--table OPERATOR_2` when importing a report that
does not include a matching operator value.

## Enjoy automating your tasks! 🎉
