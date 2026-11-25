# Markdownlint for the whole workspace

Every Markdown file in the workspace is lint-clean: 18 files, 0 issues. One command lints them all, not only the file open in the editor. The shared rules are in [`.markdownlint-cli2.jsonc`](../../.markdownlint-cli2.jsonc). The command line and the VS Code extension both use them. The engine is `markdownlint-cli2` 0.24.2, pinned as an npm dev tool in [`package.json`](../../package.json) and `package-lock.json`. `npx` is no longer used ([F130](#f130--verified--markdownlint-cli2-is-a-locked-npm-dev-tool-not-npx)).

The 407 earlier issues are fixed without changing any content or moving any link target ([F131](#f131--verified--407-issues-fixed-content-and-link-targets-unchanged)). A local VS Code task fills the Problems panel when the folder opens. It only starts once the user setting `task.allowAutomaticTasks` is `"on"`. That setting was missing, which is why problems showed only for open files ([F129](#f129--verified--folder-open-tasks-never-ran-automatic-tasks-are-off)). `CLAUDE.md` and `AGENTS.md` require 0 issues for every `.md` file created or updated.

## How to check

From the project root in PowerShell, install once with `npm ci`, then:

```powershell
npm run --silent lint:md 2>&1 | Select-String -Pattern '^(Linting|Summary)'
npm exec --offline -- markdownlint-cli2 docs/activities/2026-11-25-markdownlint-workspace.md
```

Expected result: `Linting: 18 files` and `Summary: 0 issues in 0 files` for the workspace. The single-file check of this doc should also report `Summary: 0 issues in 0 files`.

In VS Code, do this once: press Ctrl+Shift+P, choose "Tasks: Manage Automatic Tasks", then "Allow Automatic Tasks". This writes `"task.allowAutomaticTasks": "on"` to your user settings. Then run "Developer: Reload Window". After the reload, the "markdownlint: check workspace" task runs on its own. You can also run it by hand with "Tasks: Run Task". Its findings appear in Problems with the source "markdownlint (workspace)". The extension's own command, "markdownlint: Lint all Markdown files in the workspace", works too, but only when you run it by hand.

## F127 · VERIFIED · The extension lints only open files; a CLI task covers the workspace

The installed extension is `davidanson.vscode-markdownlint-0.63.0`. Its `package.json` activates it only `onLanguage:markdown` (and the related chat languages). For the whole workspace, its readme points to the `markdownlint.lintWorkspace` command, which you have to run by hand. Its bundle reports `markdownlint-cli2 v0.24.2`. The extension registers its own workspace task with `resolveTask:()=>{}`, so an entry in `tasks.json` can't change how it runs, for example to start on folder open.

So the scan uses the same engine version on its own, pinned: `npx --yes markdownlint-cli2@0.24.2`. Node is installed (`node --version` → `v24.13.0`). This adds no Python dependency and leaves `uv.lock` unchanged, but npx downloads the package from npm on first use.

Changes:

- [`.markdownlint-cli2.jsonc`](../../.markdownlint-cli2.jsonc), tracked. It enables the default rules and turns off `MD013`, which matches the extension's built-in default. It ignores `.venv`, `node_modules`, `.git`, the `.pytest_*` folders, the tool caches and `.prof`. There is no `globs` key: with one, `markdownlint-cli2 CLAUDE.md AGENTS.md` still linted the whole workspace, because the config globs are added to the file arguments.
- `.vscode/tasks.json` (gitignored, local only). It adds the task "markdownlint: check workspace", which runs `npx --yes markdownlint-cli2@0.24.2 "**/*.md"` with `runOn: folderOpen`, like the existing ruff task. Its problem matcher reads lines in the form `file:line[:col] error MDxxx/name message`. On the first run's output, the matcher regexp matched 407 lines out of 407 issue lines.
- `CLAUDE.md` and `AGENTS.md` (gitignored, local only, still identical). §5 has a new subsection, "Markdown: markdownlint": a new file must have 0 issues, and an updated file must have no more issues than before. Existing issues in lines you didn't touch stay until a separate task. Any suppression must name the rule and give a reason. §6 lists the command.

Behavior is unchanged: no Python file changed. Checked at `7890c80` with markdownlint-cli2 v0.24.2 (markdownlint v0.42.2). Before this doc existed:

```text
npx --yes markdownlint-cli2@0.24.2 "**/*.md"
Linting: 17 files
Summary: 407 issues in 4 files

npx --yes markdownlint-cli2@0.24.2 CLAUDE.md AGENTS.md docs/activities/2026-11-25-docs-folder-layout.md
Linting: 3 files
Summary: 0 issues in 0 files
```

Ruff, mypy, pytest and the golden-master compare: **NOT RUN**. Only Markdown, JSON config and gitignored editor files changed.

Later in this file: [F129](#f129--verified--folder-open-tasks-never-ran-automatic-tasks-are-off) corrects the `tasks.json` claim, and [F130](#f130--verified--markdownlint-cli2-is-a-locked-npm-dev-tool-not-npx) supersedes the `npx` commands and the CLAUDE.md rule described here.

## F128 · VERIFIED · Existing markdownlint issues (baseline, not fixed)

These counts are by file and rule, from the workspace run above:

| File | MD036 | MD033 | MD060 | MD010 | MD012 | Total |
| --- | --- | --- | --- | --- | --- | --- |
| [Modernization plan](../plans/2026-11-23-plan-modernization.md) | 237 | 12 | 12 | 3 | 0 | 264 |
| [Phase 1 baseline](2026-11-23-phase-1-behavior-baseline.md) | 72 | 65 | 0 | 2 | 1 | 140 |
| [Phase 5 reader guide](2026-11-24-phase-5-reader-guide.md) | 0 | 2 | 0 | 0 | 0 | 2 |
| [README](../../README.md) | 0 | 1 | 0 | 0 | 0 | 1 |

What the rules mean:

- **MD036:** bold text used as a heading, for example `**F40 — ...**` labels.
- **MD033:** inline HTML.
- **MD060:** inconsistent table column style.
- **MD010:** hard tabs.
- **MD012:** several blank lines in a row.

Most of these lines are old findings and recorded command output. Fixing them would rewrite old findings (§8), and some tabs may be part of recorded output. They were left unchanged.

Superseded by [F131](#f131--verified--407-issues-fixed-content-and-link-targets-unchanged): the owner approved the cleanup, and all 407 issues are fixed.

## F129 · VERIFIED · Folder-open tasks never ran: automatic tasks are off

The owner reported that problems still showed only for open files. That is expected when the folder-open task never runs. I read the code of the installed VS Code (`code --version` → `1.147.0`, `resources\app\out\vs\workbench\workbench.desktop.main.js`):

- The setting is declared as `"task.allowAutomaticTasks":{type:"string",enum:["on","off"],...,default:"off",scope:1,restricted:!0}`. Scope 1 is application, so only user settings count. A value in `.vscode/settings.json` is ignored.
- `_runWithPermission` runs folder-open tasks right away only `if(t.getValue(x6t)==="on")`. Otherwise it returns if `task.hasPromptedForAutomaticTasks.v2` is already stored. So once the prompt has been shown and dismissed, the tasks never run again. Choosing "Allow" in the prompt writes `"on"` to user settings: `n.updateValue(x6t,"on",2)`.
- `Select-String -Path "$env:APPDATA\Code\User\settings.json" -Pattern 'task\.'` printed nothing. The user settings don't set `task.allowAutomaticTasks`, so it is `"off"`. This also means the existing ruff folder-open task has not been starting on its own.

To fix it, choose "Tasks: Manage Automatic Tasks", then "Allow Automatic Tasks", then reload the window (see How to check). This is a user-wide setting. It lets every trusted workspace start its folder-open tasks, so the owner should make the change, not an agent. Whether the task then starts on reload in the owner's VS Code is **UNVERIFIED**: I can't drive the VS Code UI from here.

**Correction to F127.** F127 said a `tasks.json` entry can't make the extension's own task start on folder open. The same bundle has `_findAutoTasks`, which also resolves *customizations* with `runOn` set to folderOpen (`a.configurations.byIdentifier` → `e.getTask(...)`). VS Code also activates an extension by task type: `activationEventsGenerator` yields `` `onTaskType:${o.type}` `` for `contributes.taskDefinitions`. So a customization may work, but I didn't test it. That is **PARTIAL**. The task in `tasks.json` uses the locked CLI instead ([F130](#f130--verified--markdownlint-cli2-is-a-locked-npm-dev-tool-not-npx)), so it doesn't depend on how the extension activates.

## F130 · VERIFIED · markdownlint-cli2 is a locked npm dev tool, not npx

The owner chose a local npm dev dependency over `npx`. Changes:

- [`package.json`](../../package.json): `"private": true`, `devDependencies` `"markdownlint-cli2": "0.24.2"` (exact), and the script `"lint:md": "markdownlint-cli2 \"**/*.md\""`. It is a Node dev tool only, separate from the Python app, `pyproject.toml` and `uv.lock`.
- `package-lock.json` (lockfileVersion 3, 88 packages), made by `npm install --save-exact` with npm 11.6.2. `npm ls --depth=0` → `` `-- markdownlint-cli2@0.24.2 ``. `npm exec --offline -- markdownlint-cli2 --help` → `markdownlint-cli2 v0.24.2 (markdownlint v0.42.2)`, the same engine the extension bundles (F127).
- `.gitignore`: `node_modules/` was added. `git check-ignore -v node_modules` → `.gitignore:180:node_modules/	node_modules`.
- `.vscode/tasks.json` (local): the task now runs `npm run --silent lint:md`, with the same problem matcher and `runOn: folderOpen`.
- `CLAUDE.md` and `AGENTS.md` (local, still identical; `grep -c npx CLAUDE.md` → `0`). The rule is now that every `.md` file has 0 issues and `npm run --silent lint:md` stays at `Summary: 0 issues in 0 files`. The commands are `npm ci`, `npm run --silent lint:md` and `npm exec --offline -- markdownlint-cli2 <file>`. Changing `package.json` or `package-lock.json` needs approval, as `uv.lock` does.

With the old config, `npm run --silent lint:md` reported `Linting: 18 files` and `Summary: 407 issues in 4 files`, the same as the npx run in F127. Switching to the locked install changed no results.

## F131 · VERIFIED · 407 issues fixed; content and link targets unchanged

The fixes, by rule:

| Rule | Issues | Fix |
| --- | --- | --- |
| MD036 | 309 | Each `**Label**` paragraph (for example `**R01**`, `**W36**`, `**12**` before a command block) became a heading one level below the last real heading above it. Text unchanged. |
| MD033 `<a>` | 51 | In the Phase 1 baseline, `<a id="bNN"></a>` sat directly above `**BNN**`. The two lines became one heading `BNN`, whose automatic anchor is the same `#bnn`. Markdownlint had read each pair as one HTML paragraph, so these labels weren't in the MD036 count. |
| MD033 `<a>` | 3 | `#complete-workflow-catalogue` in the README, and `#current-guide-corrections` and `#branch-checks` in the Phase 5 guide, are stable link targets that differ from their heading slugs. Each keeps its anchor behind `<!-- markdownlint-disable-next-line MD033 -- stable link target; differs from the heading slug -->`. |
| MD033 `<details>`/`<summary>` | 26 | The collapsible evidence blocks are kept. The config allows these two elements (`"allowed_elements": ["details", "summary"]`). |
| MD010 | 5 | All 5 tabs are inside fenced blocks of recorded `git` output, for example `.gitignore:175:AGENTS.md\tAGENTS.md` and `D\trequirements.txt`. The config sets `"MD010": { "code_blocks": false }`, and the bytes are unchanged. |
| MD060 | 12 | Two delimiter rows, `\|---\|---\|---\|`, became `\| --- \| --- \| --- \|`. |
| MD012 | 1 | The baseline ended with an extra blank line, now removed. |

The new headings caused no new issues: there are no duplicate headings (MD024) and no skipped heading levels (MD001).

Evidence, checked at `deb6984` plus this change, with markdownlint-cli2 v0.24.2 (markdownlint v0.42.2):

```text
npm run --silent lint:md
Linting: 18 files
Summary: 0 issues in 0 files

git diff --numstat -- '*.md'
1       0       README.md
123     175     docs/activities/2026-11-23-phase-1-behavior-baseline.md
2       0       docs/activities/2026-11-24-phase-5-reader-guide.md
239     239     docs/plans/2026-11-23-plan-modernization.md
```

Content is unchanged. I compared each file at `HEAD` with the working tree after normalizing only the markup this cleanup touches. The normalization drops blank lines, `<a id>` lines and disable comments, removes heading `#` and whole-line `**...**`, and normalizes delimiter rows. Result: `SAME` for all 4 files (406, 3431, 65 and 3540 content lines), `files with content differences: 0`.

Links are unchanged:

- Before the cleanup, every in-repo `#fragment` link resolved (`fragment links 102, unresolved 0`), using GitHub-style heading slugs and explicit `<a id>` anchors.
- Afterwards, the check reported `checked 101 anchor links, changed or missing 0`: each link still resolves, to a line with the same text. The 102nd link is a `#L<n>` line link, which isn't a heading anchor.
- The plain relative-link check found no new broken links. Its only hits are text in inline code or recorded snippets that looks like a link (`ROOT,label` and `target`).

Behavior is unchanged: no Python file changed. `uv run --locked ruff format --check .` reported `160 files already formatted`. `uv run --locked ruff check .` reported `All checks passed!`, and `uv run --locked mypy .` reported `Success: no issues found in 144 source files`. pytest and the golden-master compare: **NOT RUN**. Only Markdown, JSON config, the npm tool files and gitignored editor files changed.

## Open items

- Owner action: allow automatic tasks once (see How to check), then confirm that the Problems panel lists Markdown findings without opening a file. F129 marks this **UNVERIFIED** until then.
- `ruff format --check` reported 160 files here and 158 in F126. `ruff check --show-files` lists 145 files, all tracked, and `node_modules` and `.vscode` are skipped by `.gitignore`. The cause of the difference is **UNVERIFIED**. No Python file changed in this task, and the gate passes.
