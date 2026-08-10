# Unity Catalog access policy

Enforced by [catalog-guard.ps1](catalog-guard.ps1), wired in via `.claude/settings.json` as a `PreToolUse` hook on `Bash`/`PowerShell`.

## Rule

Claude may read/write Unity Catalog data only in:

- `sandbox_others`

Claude is blocked from any Databricks CLI, SQL, or Unity Catalog REST command that references:

- `system` — platform-managed catalog
- `samples` — Databricks sample datasets
- `gops_dev` — owned by an admin group, not this project
- `sandbox_hackaton` — a different sandbox, out of scope for this project

The block applies to any operation that targets one of those catalogs specifically (reads and writes alike) — not just mutating operations. Generic enumeration commands that don't name a catalog (e.g. `databricks catalogs list`) are unaffected.

Non-Databricks commands are untouched: the hook only evaluates commands that look like Databricks CLI calls, SQL, or Unity Catalog REST/curl calls, so it won't false-positive on unrelated shell commands that happen to contain words like "system".

## Changing the policy

Edit the `$allowedCatalog` / `$disallowed` lists in [catalog-guard.ps1](catalog-guard.ps1), then run `/hooks` (or restart) to reload — the settings watcher only picks up changes to files that existed when the session started.

## History

- 2026-08-10: Initial policy. Workspace has 5 catalogs (`system`, `samples`, `gops_dev`, `sandbox_hackaton`, `sandbox_others`); user authorized `sandbox_others` only for this project.
