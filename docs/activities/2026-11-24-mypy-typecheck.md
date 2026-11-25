# Type-check TaskBot with mypy in the terminal and VS Code

mypy reports **no issues in all 142 source files**. The terminal and VS Code now use the same checker: the project's own mypy 2.4.1, running on the project's Python 3.14. mypy is a dev dependency, and `python_version = "3.14"` is set in the mypy config. [Dependency](../../pyproject.toml#L19) · [mypy config](../../pyproject.toml#L25-L30)

The 150 problems VS Code showed before this change came from two sources. Most were real type errors in revision `290780f`, fixed by type-only changes. The rest came from the editor setup: an outdated mypy run and a mypy hosted on the wrong Python version. F95 explains the cause. F97 shows the fixes keep the app's behavior unchanged.

## How to check types

1. **Terminal.** From the project folder, run:

   ```powershell
   uv sync
   uv run mypy .
   ```

   Expected output: `Success: no issues found in 142 source files`.

2. **VS Code.** Install the **Mypy Type Checker** extension (`ms-python.mypy-type-checker`). Remove the older **Mypy** extension (`matangover.mypy`) so two checkers don't compete. Select `.venv` as the Python interpreter. `.vscode/` is git-ignored ([.gitignore:173](../../.gitignore#L173)), so each developer adds these lines to their own `.vscode/settings.json`:

   ```json
   "mypy-type-checker.importStrategy": "fromEnvironment",
   "mypy-type-checker.reportingScope": "workspace"
   ```

   The extension checks the whole project whenever a Python file is opened or saved. A full check takes about 3–7 seconds.

3. **If an error stays after you fix it**, run **Ctrl+Shift+P → "Mypy: Restart Server"**. The extension doesn't always clear old entries once the error count reaches zero. See F96.

## F95 · VERIFIED · Why VS Code showed 150 problems

- **The old extension checked with mypy running on Python 3.12.** `matangover.mypy` 0.4.2 ran `dmypy` from the globally installed uv tool: mypy 2.4.1, installed on Python 3.12.11. It passed `--python-executable .venv\Scripts\python.exe` so mypy could find the project's packages. With no `python_version` setting, mypy treats code as written for the Python it runs on.
- **`except A, B:` is valid only from Python 3.14** (PEP 758). The code uses it 15 times, for example [main.py:159](../../main.py#L159). Under a 3.12 target, mypy reports each one as `Multiple exception types must be parenthesized`. Results for a one-file probe with the same mypy:

  | Target version | Result |
  | --- | --- |
  | `--python-version 3.12` | `error: Multiple exception types must be parenthesized  [syntax]` |
  | `--python-version 3.13` | same error |
  | `--python-version 3.14` | `Success: no issues found in 1 source file` |

  The project requires Python 3.14 (`requires-python = ">=3.14"`), so this syntax is valid and stays. Setting `python_version = "3.14"` makes mypy accept it.
- **The panel was out of date.** The old extension's log shows three runs, all in the editor session that started 2026-11-23 at 01:06. The mypy config and type fixes were saved later that day, between 23:32 and 23:39. The extension never rechecked, so the panel kept showing the old results.
- **The remaining errors were real.** Different mypy setups agree that revision `290780f` had type errors:

  | Code | mypy used | Result |
  | --- | --- | --- |
  | `290780f` | global 2.4.1 on Python 3.12, old extension's arguments | `Found 121 errors in 30 files`, including the 15 syntax errors, plus 61 notes |
  | `290780f` | extension's bundled 1.15.0 on Python 3.14 | 107 errors in 27 files, no syntax errors, plus 61 notes. mypy's own summary line misreports this as `in 1 file` |
  | current | global 2.4.1 on Python 3.12, old extension's arguments | `Success: no issues found in 142 source files` |
  | current | 2.4.1 on Python 3.14, in a temporary environment | `Success: no issues found in 142 source files` |
  | current | project `.venv` 2.4.1 via `uv run mypy .` | `Success: no issues found in 142 source files` |

- **PARTIAL:** the panel's count of 150 was not matched exactly against the 121 errors and 61 notes above. The messages are the same, for example `Need type annotation for "_counts"` and the 15 syntax errors.

## F96 · VERIFIED · Mypy Type Checker extension behavior

These come from the extension's code (version 2026.8.0, `bundled/tool/lsp_server.py`) and from its log in VS Code's Output panel.

- **By default it checks only open files.** The default `reportingScope` is `"file"`: mypy runs only when a file is opened or saved, and only for that file (`lsp_server.py` L172–L191, L752–L756). An empty Problems panel can therefore mean "nothing checked yet". The `"workspace"` setting above makes each run cover the whole project.
- **By default it uses its own bundled mypy 1.15.0.** On the current code, that older mypy reports one error that 2.4.1 doesn't: `Unpacked dict entry 0 has incompatible type "dict[str, Any]"` at [reporter.py:677](../../src/web/reporter.py#L677). That line has been unchanged since March. `"importStrategy": "fromEnvironment"` makes the extension use `.venv`'s mypy instead. Its log confirms `FOUND mypy==2.4.1`.
- **Old entries can stay once errors reach zero.** When mypy prints nothing, the extension clears only the file that triggered the run (`lsp_server.py` L326–L366). Other files keep their old entries until the extension restarts. This happened in the probe test below. "Mypy: Restart Server" clears them, as does changing its settings or editing `pyproject.toml`.
- **Files outside the project folder use your global VS Code settings.** Here those were still the defaults: single-file checks with the bundled mypy. Opening such a file can add problems that have nothing to do with TaskBot, and closing its tab removes them.
- **Probe test.** A temporary file with a deliberate error was added at the project root, then deleted:

  ```python
  def probe() -> int:
      try:
          pass
      except ValueError, TypeError:  # must NOT be reported
          pass
      return "not an int"  # must be reported
  ```

  The panel showed exactly one problem: `Incompatible return value type (got "str", expected "int")  [return-value]` on line 7. The `except` line wasn't flagged. After the file was deleted, the next run printed nothing, yet the probe's entry stayed until the extension restarted. After the restart, no project entries remained.

## F97 · VERIFIED · Type fixes keep behavior unchanged

The fixes touch 18 source files, 10 test files and `pyproject.toml`, on top of `290780f`. Most add annotations, `cast()`, `Literal` types or `# type: ignore[code]` comments, which don't run any differently. The changes that touch code that runs are listed below with the reason they behave the same.

| Change | Why behavior is unchanged |
| --- | --- |
| `_stage_row` reads the journal through `cast(QuotaJournal, self._journal)` at each use. [report_syncer.py:62-73](../../src/infrastructure/database/report_syncer.py#L62-L73) | An earlier draft used `assert`, which would raise `AssertionError` instead of the original `AttributeError` if a row arrived after `close()`. The caller catches and re-raises any exception, so the type could reach logs. [reporter.py:1138](../../src/web/reporter.py#L1138). `cast` does nothing at runtime, and keeping it at each use keeps the read order the same. |
| `reports is not None` replaces `cached` [reporter.py:1353](../../src/web/reporter.py#L1353) | `reports` is `None` only when `cached` is false. `_meta_row_reports()` always returns a dict. [reporter.py:1269](../../src/web/reporter.py#L1269) |
| `connection is None` replaces `owns_connection` [operator_store.py:613](../../src/infrastructure/database/operator_store.py#L613) | `owns_connection` was defined as `connection is None`. |
| `not a or not b or not c` replaces `not all([a, b, c])` [solver.py:143](../../src/pipelines/slider/solver.py#L143) | Same truth test on values already computed. |
| `np.asarray(..., dtype=np.float32)` replaces `np.float32(...)` [matching.py:417](../../src/vision/puzzle/matching.py#L417) | Same dtype, shape and values on a test input. |
| `drawContours(..., (255,), -1)` replaces `255` [preprocessing.py:156](../../src/vision/puzzle/preprocessing.py#L156) | Identical masks on a test contour, 387 pixels filled in both. |
| `normalize_minmax()` wraps `cv2.normalize(img, None, lo, hi, NORM_MINMAX)` [preprocessing.py:11](../../src/vision/puzzle/preprocessing.py#L11) | It makes the same call. Only the type stub needed the ignore. |
| `sys.platform != "win32" and os.name == "posix"` [quota_journal.py:24](../../src/infrastructure/database/quota_journal.py#L24) | `os.name` is never `"posix"` on Windows, so the result is the same on every platform. |
| Explicit `browser is None` check [export_service.py:460](../../src/infrastructure/sessions/export_service.py#L460) | Raises the same `AttributeError` message the original line would have raised. |
| `frame.f_back if frame is not None` [logging_utils.py:261](../../src/logging_utils.py#L261) | CPython always returns a frame here. |
| `_LOAD_STATE: Final = "load"` [transaction_processor.py:55](../../src/orchestration/transaction_processor.py#L55) | Same value. |

The test changes add annotations, `cast()` and `monkeypatch.setattr`. No assertion changed.

| Check | Result |
| --- | --- |
| Full suite on `290780f` (exported copy) | `1440 passed, 5 skipped in 54.24s` |
| Full suite with the type fixes | `1440 passed, 5 skipped in 50.82s` |
| Full suite after adding the mypy dependency | `1440 passed, 5 skipped in 50.47s` |
| Collected test IDs, before and after | 1445 and 1445, identical lists |

The five skips are the PostgreSQL tests, which run only when `TASKBOT_QUOTA_TEST_DB` is set. On the machine used, pytest's default temp folder (`%TEMP%\pytest-of-<user>`) raised `PermissionError` for 284 tests that use `tmp_path`. Every run above therefore passed `--basetemp` pointing to a writable folder:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp <writable-folder>
```

## F98 · VERIFIED · Dependency change

`uv add --dev "mypy>=2.4.1"` added five packages and changed no existing version:

| Package | Version |
| --- | --- |
| mypy | 2.4.1 |
| mypy-extensions | 1.2.0 |
| librt | 0.17.0 |
| pathspec | 1.1.1 |
| ast-serialize | 0.13.1 |

`uv.lock` also split its platform markers by `python_full_version` around 3.15. No existing package line was removed.

## Open items

- **UNVERIFIED · Old-vs-new app output comparison.** The type fixes were not checked by comparing database rows and report files from paired whole-app runs. That requires running the app against the test configuration.
- **Not committed at time of writing.** The type fixes, mypy config, dependency and this document are working-tree changes on `modernize`.
- **Leftovers from the old setup.** The global mypy tool still runs on Python 3.12, and the project no longer needs it. The old extension can leave an orphaned `dmypy` process running; end it in Task Manager or with `taskkill`.
