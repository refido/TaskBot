# Markdownlint for the whole workspace

Every Markdown file in the workspace can now be linted in one run, not just the file open in the editor. The shared rules are in [`.markdownlint-cli2.jsonc`](../../.markdownlint-cli2.jsonc). The command line and the VS Code extension both use them. A local VS Code task runs the scan when the folder opens and lists the results in the Problems panel. `CLAUDE.md` and `AGENTS.md` now require markdownlint for every `.md` file created or updated. The first scan found 407 existing issues in 4 of the 17 files. They are recorded below and left for a separate task.

## How to check

From the project root in PowerShell:

```powershell
npx --yes markdownlint-cli2@0.24.2 "**/*.md" 2>&1 | Select-String -Pattern '^(Linting|Summary)'
npx --yes markdownlint-cli2@0.24.2 docs/activities/2026-11-25-markdownlint-workspace.md
```

Expected result: `Linting: 18 files` and `Summary: 407 issues in 4 files` for the workspace, then `Summary: 0 issues in 0 files` for this doc.

In VS Code, press Ctrl+Shift+P, choose "Tasks: Run Task", then "markdownlint: check workspace". The Problems panel then lists the findings with the source "markdownlint (workspace)".

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

## Open items

- Owner decision: should these 407 issues be cleaned up in a separate task, or kept as historical text? Turning bold labels into headings (MD036) would change the anchors that other docs link to.
- `npx --yes` downloads the pinned package from npm the first time it runs. If the owner prefers a locked install, a `package.json` with a lockfile needs approval as a new dependency.
- VS Code runs folder-open tasks only once automatic tasks are allowed for the workspace. The existing ruff task already depends on this.
