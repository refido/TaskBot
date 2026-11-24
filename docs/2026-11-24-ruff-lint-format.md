# Lint and format TaskBot with Ruff in the terminal and VS Code

TaskBot passes `ruff check` and `ruff format --check` on all 142 Python files. The terminal and VS Code now use the same binary: the project's own Ruff 0.17.6 in `.venv`. [Dependency](../pyproject.toml#L23) · [Ruff settings](../pyproject.toml#L33-L36)

The Ruff extension only checks files that are visible in an editor tab, and none of its settings change that. A VS Code task fills that gap by running Ruff on the whole project and listing the results in the Problems panel. F100 covers the extension's limit. F101 and F102 explain why each fix keeps behavior unchanged.

## How to check and format

1. **Terminal.** From the project folder:

   ```powershell
   uv run ruff check .            # lint, expected: All checks passed!
   uv run ruff format --check .   # expected: no "Would reformat" lines
   uv run ruff format .           # reformat
   uv run ruff check --fix .      # apply safe lint fixes
   ```

   **Never combine `--fix` with a partial `--select`** while the unused-suppression rule `RUF100` is active. Rules left out of the selection make the existing `# noqa` comments look unused, and Ruff deletes them. See F101.

2. **VS Code.** Use the **Ruff** extension (`charliermarsh.ruff`) with `.venv` as the selected interpreter. `.vscode/` is git-ignored ([.gitignore:173](../.gitignore#L173)), so each developer adds this to `.vscode/settings.json`:

   ```json
   "ruff.importStrategy": "fromEnvironment"
   ```

   Also create `.vscode/tasks.json` with the task below. Run it with **Ctrl+Shift+P → "Tasks: Run Task" → "ruff: check workspace"**. When VS Code asks about automatic tasks, allow them; the task then runs each time the folder opens.

   ```jsonc
   {
       "version": "2.0.0",
       "tasks": [
           {
               "label": "ruff: check workspace",
               "type": "process",
               "command": "uv",
               "args": ["run", "ruff", "check", "--exit-zero", "--output-format", "concise", "."],
               "options": { "cwd": "${workspaceFolder}" },
               "presentation": { "reveal": "never", "revealProblems": "onProblem", "panel": "dedicated", "clear": true },
               "problemMatcher": [
                   {
                       "owner": "ruff-workspace",
                       "source": "Ruff (workspace)",
                       "fileLocation": ["relative", "${workspaceFolder}"],
                       "severity": "warning",
                       "pattern": {
                           "regexp": "^(.+?):(\\d+):(\\d+): ([A-Z]+[0-9]+) (?:\\[\\*\\] )?(.*)$",
                           "file": 1, "line": 2, "column": 3, "code": 4, "message": 5
                       }
                   },
                   {
                       "owner": "ruff-workspace-syntax",
                       "source": "Ruff (workspace)",
                       "fileLocation": ["relative", "${workspaceFolder}"],
                       "severity": "error",
                       "pattern": {
                           "regexp": "^(.+?):(\\d+):(\\d+): (invalid-syntax): (.*)$",
                           "file": 1, "line": 2, "column": 3, "code": 4, "message": 5
                       }
                   }
               ],
               "runOptions": { "runOn": "folderOpen" }
           }
       ]
   }
   ```

   The task's results are a snapshot, so rerun it after large edits or a `git pull`. A file that is open and has a problem is listed twice: live by the extension ("Ruff") and by the task ("Ruff (workspace)").

3. **Suppressing a finding.** Fix the code when the fix doesn't change behavior. Otherwise follow the project convention `# noqa: CODE - reason.`, for example [session_state.py:19](../src/web/session_state.py#L19):

   ```python
   except Exception:  # noqa: BLE001, S110 - login detection is best effort.
   ```

## F99 · VERIFIED · Where the Ruff problems came from

- **No Ruff configuration existed.** There was no `[tool.ruff]`, no `ruff.toml` in the project, its parent folders or the user config folder, and no `ruff.*` VS Code setting. Ruff therefore used its built-in defaults. In 0.17.6 those defaults enable **407 rules**, much broader than older Ruff versions. Most come from `PYI`, `UP`, `F`, `RUF`, `PLE`, `B` and `SIM`. `I001` (unsorted imports) and `PLC0414` (useless import alias) are among them. `ruff check --show-settings` also showed Python 3.14 as the target, read from `requires-python`.
- **The extension used its bundled Ruff.** Ruff wasn't installed in `.venv`, so the extension log reported `Falling back to bundled executable`. That bundled copy was also 0.17.6.
- **Starting point.** On the code at the time, with the type fixes from [the mypy guide](2026-11-24-mypy-typecheck.md) applied, `ruff check .` printed `Found 88 errors.` in 35 files, and `ruff format --check .` printed `66 files would be reformatted, 83 files already formatted`.

  | Rule | Count | Rule | Count |
  | --- | ---: | --- | ---: |
  | `RUF046` unnecessary int cast | 32 | `UP035` deprecated import | 2 |
  | `BLE001` blind except | 17 | `UP045` `Optional[X]` | 2 |
  | `I001` unsorted imports | 11 | `S110` try-except-pass | 1 |
  | `UP006` `DefaultDict` | 5 | `S112` try-except-continue | 1 |
  | `PLW1510` `subprocess.run` without `check` | 4 | `RUF022` unsorted `__all__` | 1 |
  | `C408` `dict()` call | 4 | `RUF034` useless if-else | 1 |
  | `UP037` quoted annotation | 3 | `RUF100` unused `noqa` | 1 |
  | `PLC0414` useless import alias | 3 | | |

## F100 · VERIFIED · The extension only checks files visible in a tab

- **Observed.** Before the fixes, the Problems panel listed 4 Ruff problems, all in `main.py`, the only Python file open in a tab. Running the same binary on the whole project found 88 problems in 35 files.
- **Cause in the extension's code.** `charliermarsh.ruff` 2026.98.0 requests diagnostics only for documents that match its document selector **and** are visible in a tab (`languages.match(...) > 0 && isVisible(doc)` in `dist/extension.js`). It discards results for documents that aren't visible. A file opened in the background, without a tab, gets no diagnostics, even after its content changes on disk.
- **No setting changes this.** The extension's settings cover the binary, interpreter, configuration and exclusions, but nothing like the mypy extension's `reportingScope`.
- **Positive control.** One unused import was appended to `main.py` while it was open in a tab. The panel showed `Ruff F811: Redefinition of unused 'os' from line 2` within moments. The line was then removed, and the entry disappeared. Afterwards `main.py` had the same MD5 hash (`e04f82ba…`) as before the test. A probe file opened without a tab got no Ruff diagnostics, which matches the code above.
- **Switching to the project's binary.** Changing a `ruff.*` setting restarts the extension. Its log then showed `Using the Ruff binary: d:\MyProject\TaskBot\.venv\Scripts\ruff.exe` and `Found Ruff 0.17.6`.
- **Why the task doesn't use watch mode.** `ruff check --watch` prints its summary **before** the problems in each cycle:

  ```text
  [00:56:54 AM] File change detected...
  [00:56:55 AM] Found 1 error. Watching for file changes.
  _ruff_probe_tmp.py:1:8: F401 [*] `os` imported but unused
  ```

  A VS Code watch-mode matcher would treat the summary line as the end of a cycle and handle the problems that follow unreliably. A run-once task avoids this, because each run replaces the previous run's results. `--exit-zero` keeps a run with findings from showing up as a failed task.
- **Matcher test.** Both patterns were tested with Node (VS Code's regular-expression engine) against real Ruff output: rule violations matched as warnings, `invalid-syntax` lines as errors, and summary lines were ignored. The task command prints `All checks passed!` with exit code 0 on the current code.

## F101 · VERIFIED · How each finding was resolved without changing behavior

| Rule | Resolution | Why behavior is unchanged |
| --- | --- | --- |
| `BLE001` ×17, `S110`, `S112` | `# noqa` with a reason at each site, e.g. [transaction_processor.py:413](../src/orchestration/transaction_processor.py#L413), [db_management.py:92](../scripts/db_management.py#L92) | Each is a deliberate catch-all: a fallback, a cleanup step, error capture, a CLI boundary, or a test helper passing failures back to the test thread. Narrowing them would change behavior. The code already had 46 inline suppressions in this style, 45 of them for `BLE001`. |
| `RUF046` ×32 | Disabled for `src/vision/**` and `src/pipelines/slider/**` only ([pyproject.toml:33-36](../pyproject.toml#L33-L36)) | No code changed. With NumPy 2, `round()` returns a Python `int` for `float32`, `float64` and `int64` scalars, so most casts are currently redundant. Proving that for all 32 sites would mean tracing every value's type. |
| `I001` ×11 | Ruff's safe fix | Imports were only rewrapped or had an extra blank line removed; none was reordered. In `main.py`, the aliased import became four statements that bind the same four names from the same module, in the same order. Ruff's `combine-as-imports` option would avoid the split but raises the `I001` count from 11 to 18. |
| `PLC0414` ×3 | `# noqa` ([main.py:20](../main.py#L20), [26](../main.py#L26), [29](../main.py#L29)) | `X as X` marks compatibility re-exports, per the comment above them. Removing the alias could let the unused-import fix delete names other modules use. |
| `UP006`, `UP035`, `UP037`, `UP045` | Ruff's safe fixes | They only change type annotations and where `Iterator` is imported from. Nothing reads these annotations at runtime: the three `signature()` calls target other functions, and loguru doesn't inspect annotations. `puzzle_solver.py` and `analytics.py` use `from __future__ import annotations`. |
| `C408` ×4 (tests) | Ruff's fix, marked unsafe, applied after review | `dict(a=1)` and `{"a": 1}` build the same dict, with the same keys in the same order. |
| `PLW1510` ×4 (tests) | Added `check=False` | `False` is already the default. These tests check `returncode` themselves. |
| `RUF022` | `__all__` sorted in `src/vision/puzzle/__init__.py` | Only the order of names in `__all__` changes. |
| `RUF034` | `# noqa` ([matching.py:532](../src/vision/puzzle/matching.py#L532)) | Keeps the per-mode weights table explicit. |
| `RUF100` | Removed an unused `# ruff: noqa: DTZ001` | `DTZ001` isn't enabled. Only that comment was removed: the `noqa` count went from 68 to 67. |

**Suppressions nearly lost.** A preview with `--select C408,PLW1510,RUF022,RUF100,UP006,UP035,UP037,UP045 --fix --unsafe-fixes --diff` showed Ruff about to delete all 46 existing inline suppressions: 45 for `BLE001` and one `# noqa: TRY004`. Those rules weren't in the selection, so `RUF100` treated the comments as unused. It was only a preview, so nothing was written. The fix was then applied with the full rule set. Run against the current code, the same preview lists all 67 suppressions for deletion.

## F102 · VERIFIED · Formatting

- **Line length.** The default of 88 gives the smallest diff, so the code was already mostly written for 88. The project keeps that default.

  | Line length | Files changed | Lines changed |
  | ---: | ---: | ---: |
  | 88 | 66 | 3,300 |
  | 100 | 91 | 3,995 |
  | 110 | 96 | 4,466 |
  | 120 | 97 | 4,841 |

- **Result.** `ruff format .` reformatted 65 files. One of the original 66 was already fixed by the import rewrapping. Most changes are in tests. In the 88-character preview, `test_reporter_meta_payload.py` had the most, with 289 changed lines.
- **`except` style.** With Python 3.14 as the target, the formatter rewrites `except (A, B):` as `except A, B:`. That is where this syntax in the code comes from. mypy accepts it because of `python_version = "3.14"`. See [the mypy guide](2026-11-24-mypy-typecheck.md).
- **Markdown is formatted too.** Ruff 0.17 also formats Python code blocks inside Markdown. Its 149-file count at the time was the 142 `.py` files plus `README.md` and six files in `docs/`; this document adds one more. None of the Markdown files changed. Python examples in these docs, including this one, must stay Ruff-formatted.

## F103 · VERIFIED · Checks

Each `.py` file was compared by its syntax tree in three snapshots: before Ruff, after lint fixes, and after formatting. The comparison ignores line and column positions, so a pure layout change shows as identical:

```python
import ast


def same_tree(before: str, after: str) -> bool:
    return ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))
```

| Check | Result |
| --- | --- |
| Formatting step, syntax-tree comparison | 142 of 142 files identical |
| Lint step, syntax-tree comparison | 11 files differ, all intended: `main.py` (import split), `analytics.py`, `logging_utils.py`, `puzzle_solver.py` (annotations), `vision/puzzle/__init__.py` (`__all__` order), and 6 test files (`check=False`, `dict()` → `{}`) |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `149 files already formatted` |
| `uv run mypy .` | `Success: no issues found in 142 source files` |
| Full test suite | `1440 passed, 5 skipped in 52.88s`, same 1445 test IDs as before |
| Dependency change | `uv add --dev "ruff>=0.17.6"` added only `ruff==0.17.6` |

The test run used `--basetemp`, for the reason given in [the mypy guide](2026-11-24-mypy-typecheck.md#f97--verified--type-fixes-keep-behavior-unchanged). The five skips are the opt-in PostgreSQL tests.

## Open items

- **UNVERIFIED · Workspace task inside VS Code.** The task's command, patterns and JSON were checked, but it hasn't been run from VS Code yet.
- **UNVERIFIED · Old-vs-new app output comparison.** Database rows and report files were not compared across paired whole-app runs.
- **Log line numbers change.** `log_print` records the caller's line number ([logging_utils.py:263](../src/logging_utils.py#L263)). After reformatting, diagnostic logs show different line numbers for the same events.
- **Ruff's defaults change between versions.** Upgrading Ruff can enable new rules. Review `ruff check` output after an upgrade, or list the selected rules explicitly in `pyproject.toml`.
- **Not committed at time of writing.** The Ruff work is unstaged: 75 files, including `pyproject.toml` and `uv.lock`. CLAUDE.md asks for formatting in its own commit, so commit the lint changes and the `ruff format` changes separately.
- **Format on save is not enabled.** To keep files formatted while editing, set Ruff as the default Python formatter and turn on format on save in your local VS Code settings.
