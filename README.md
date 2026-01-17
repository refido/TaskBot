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

### 3. Run the Bot

Forget about venv\Scripts\activate. With uv, you simply "run" the command, and it handles the environment in the background.

To execute the main script:

```bash
uv run main.py
```

## Enjoy automating your tasks! 🎉
