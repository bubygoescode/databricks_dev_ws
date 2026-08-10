# Unity Catalog access policy

Enforced by [catalog-guard.ps1](catalog-guard.ps1), wired in via `.claude/settings.json` as a `PreToolUse` hook on `Bash`/`PowerShell`.

## Rule

Claude may read/write Unity Catalog data freely only in:

- `sandbox_others`

Claude has **read-only** access to (temporary — see below):

- `samples` — Databricks-provided sample datasets. Reads/lists/describes/SELECTs are allowed; any CREATE/DROP/ALTER/INSERT/UPDATE/DELETE/MERGE/TRUNCATE/GRANT/REVOKE *targeting* `samples` is blocked. Reading FROM `samples` while writing INTO `sandbox_others` (e.g. `CREATE TABLE sandbox_others.x AS SELECT * FROM samples.y`) is explicitly allowed — the guard checks which catalog is actually the DDL/DML target, not just which catalog names appear anywhere in the statement.

Claude is fully blocked (no access, read or write) from:

- `system` — platform-managed catalog
- `gops_dev` — owned by an admin group, not this project
- `sandbox_hackaton` — a different sandbox, out of scope for this project

Generic enumeration commands that don't name a catalog (e.g. `databricks catalogs list`) are unaffected by any of the above.

### Why `samples` is temporarily read-only

The SCO Agent POC's real data source is a production O365 mailbox, which is too risky/premature to wire up this early. Instead, we're using `samples.wanderbricks` as a structural stand-in (free-text support logs + booking create/update lifecycle + host/property reference data) to prove the spec-driven pipeline end-to-end before touching production email. `samples.wanderbricks.*` was copied into `sandbox_others.bronze_datasample_wanderbricks` on 2026-08-10 (7 tables: `customer_support_logs`, `bookings`, `booking_updates`, `properties`, `hosts`, `users`, `property_images`). Once that copy is complete and stable, read access to `samples` can likely be revoked again — ask before removing it in case more sampling is still needed.

## False-positive handling (important for anyone editing the hook)

The guard only evaluates commands that look Databricks/SQL-related (contains "databricks", SQL verbs, "unity-catalog", etc.) — see `$isDatabricksContext` in the script. Two false-positive classes have already bitten this hook and been fixed; keep them in mind before "fixing" it again:

1. **Git commands** are exempted outright (first token `git`) — commit messages/PR text mentioning catalog names or "Databricks" in prose must not be blocked.
2. **`system` collides with the .NET `System.*` namespace** (`[System.IO.File]`, `System.Text.Encoding`, etc.), which shows up constantly in PowerShell. `system` is matched with a dedicated pattern requiring an actual catalog-style reference (dot-qualified and not a known .NET namespace/type word, or an explicit `USE CATALOG system` / CLI-subcommand-target phrase) — not a bare `\bsystem\b`.

When testing the hook manually, **never inline a realistic test command or a descriptive label containing trigger words directly in the outer Bash/PowerShell command** — the hook scans that outer command too and will block your own test harness. Write test payloads (and any labels describing what they test) to files first via the Write tool, then pipe them in by path only.

## Changing the policy

Edit the `$allowedCatalog` / `$fullyBlocked` / `$readOnlyCatalogs` lists in [catalog-guard.ps1](catalog-guard.ps1). Script edits take effect immediately (no reload needed — each hook invocation re-reads the file from disk). Only changes to `.claude/settings.json` itself (the hook wiring) need `/hooks` or a restart to pick up.

## History

- 2026-08-10: Initial policy. Workspace has 5 catalogs (`system`, `samples`, `gops_dev`, `sandbox_hackaton`, `sandbox_others`); user authorized `sandbox_others` only for this project.
- 2026-08-10: Made `samples` temporarily read-only (was fully blocked) to source synthetic data for the SCO Agent POC. Fixed two false-positive classes: git commands, and `system` colliding with the .NET namespace.
