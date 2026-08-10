$ErrorActionPreference = 'Stop'

$stdin = [Console]::In.ReadToEnd()
if (-not $stdin) { exit 0 }

try {
    $payload = $stdin | ConvertFrom-Json
} catch {
    exit 0
}

$cmd = $payload.tool_input.command
if (-not $cmd) { exit 0 }

$cmdLower = $cmd.ToLower()

# Git operations never touch Unity Catalog directly, even when commit messages or PR
# text happen to mention catalog names or "Databricks" in prose. Skip them outright.
$firstToken = ($cmd.Trim() -split '\s+')[0] -replace '\.exe$', ''
if ($firstToken -match '^git$') { exit 0 }

$allowedCatalog = 'sandbox_others'
$fullyBlocked = @('system', 'gops_dev', 'sandbox_hackaton')
# TEMPORARY (see guardrails/CATALOG_POLICY.md): samples is read-only, not fully blocked,
# while we explore it as a stand-in data source for the SCO Agent POC instead of live O365 mail.
$readOnlyCatalogs = @('samples')

# Only evaluate commands that actually look like Databricks / SQL / Unity Catalog operations,
# so ordinary shell commands that happen to contain words like "system" or "samples" are left alone.
$isDatabricksContext = (
    ($cmdLower -match '\bdatabricks\b') -or
    ($cmdLower -match '\bunity-catalog\b') -or
    ($cmdLower -match '/api/2\.[01]/unity-catalog') -or
    ($cmdLower -match '\bcloud\.databricks\.com\b') -or
    ($cmdLower -match '\bazuredatabricks\.net\b') -or
    ($cmdLower -match '\b(select|insert|update|delete|create|drop|alter|grant|revoke|merge|truncate)\b.*\bcatalog\b') -or
    ($cmdLower -match 'use\s+catalog') -or
    ($cmdLower -match 'show\s+(catalogs|schemas|tables)')
)

if (-not $isDatabricksContext) { exit 0 }

function Block([string]$reason) {
    $result = @{
        continue      = $false
        stopReason    = $reason
        systemMessage = $reason
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = $reason
        }
    } | ConvertTo-Json -Depth 5 -Compress
    Write-Output $result
    exit 0
}

# "system" collides with the ubiquitous .NET namespace ([System.IO], System.Text.Encoding,
# New-Object System.*, etc.), which shows up constantly in PowerShell that has nothing to do
# with the Databricks "system" catalog. Give it a precise pattern instead of a bare \bsystem\b:
# either an explicit catalog-targeting phrase, or a dot-qualified reference whose next segment
# is NOT a common .NET namespace/type word.
$dotNetWords = 'io|text|net|collections|diagnostics|management|security|threading|data|xml|' +
               'reflection|environment|globalization|linq|windows|drawing|configuration|runtime|' +
               'web|object|convert|console|exception|array|string|int32|int64|int16|boolean|byte|' +
               'datetime|guid|uri|version|type|activator|appdomain|math|char|decimal|double|single'
$systemCatalogPatterns = @(
    "\bsystem\.(?!(?:$dotNetWords)\b)[a-z_][a-z0-9_]*",
    'use\s+catalog\s+system\b',
    'catalog\s+["'']?system["'']?\s',
    "(catalogs|schemas|tables|volumes|grants)\s+(get|list|delete|update|create)\s+.*\bsystem\b"
)

foreach ($catalog in $fullyBlocked) {
    if ($catalog -eq 'system') {
        $isReferenced = $false
        foreach ($pat in $systemCatalogPatterns) {
            if ($cmdLower -match $pat) { $isReferenced = $true; break }
        }
        if (-not $isReferenced) { continue }
    } elseif ($cmdLower -notmatch "\b$catalog\b") {
        continue
    }

    Block("BLOCKED by project guardrail: catalog '$catalog' is out of scope for this project. " +
          "Claude is only authorized to read/write Unity Catalog data in '$allowedCatalog'. " +
          "This command references '$catalog' in what looks like a Databricks/SQL/Unity Catalog operation. " +
          "See guardrails/CATALOG_POLICY.md. If this catalog genuinely needs to be touched, ask the user to update it.")
}

$mutatingCliSubcommands = @(
    'catalogs\s+(delete|update|create)',
    'schemas\s+(create|delete|update)',
    'tables\s+delete',
    'volumes\s+(create|delete|update)',
    'grants\s+update',
    'external-locations\s+(create|delete|update)',
    'storage-credentials\s+(create|delete|update)'
)

foreach ($catalog in $readOnlyCatalogs) {
    if ($cmdLower -notmatch "\b$catalog\b") { continue }

    # SQL: only block when the read-only catalog is the actual DDL/DML *target*
    # (e.g. "create table samples.x"), not merely a read source elsewhere in the
    # statement (e.g. "create table sandbox_others.x as select * from samples.y",
    # which is a legitimate copy-into-sandbox and must NOT be blocked).
    $sqlTargetPatterns = @(
        "create\s+(table|schema|volume|catalog)\s+(if\s+not\s+exists\s+)?$catalog\.",
        "drop\s+(table|schema|volume|catalog)\s+(if\s+exists\s+)?$catalog\.",
        "alter\s+(table|schema|volume|catalog)\s+$catalog\.",
        "insert\s+(into|overwrite)\s+$catalog\.",
        "update\s+$catalog\.",
        "delete\s+from\s+$catalog\.",
        "merge\s+into\s+$catalog\.",
        "truncate\s+table\s+$catalog\.",
        "grant\s+.*\son\s+.*$catalog\.",
        "revoke\s+.*\son\s+.*$catalog\."
    )
    $isMutating = $false
    foreach ($pat in $sqlTargetPatterns) {
        if ($cmdLower -match $pat) { $isMutating = $true; break }
    }

    # Databricks CLI: the object right after a mutating subcommand IS the target,
    # so co-occurrence with the subcommand is already target-specific here.
    if (-not $isMutating) {
        foreach ($pat in $mutatingCliSubcommands) {
            if ($cmdLower -match $pat) { $isMutating = $true; break }
        }
    }

    if ($isMutating) {
        Block("BLOCKED by project guardrail: catalog '$catalog' is READ-ONLY for this project (temporary exploration access). " +
              "Writes/mutations targeting '$catalog' are not authorized, though reading FROM it (e.g. into sandbox_others) is fine. " +
              "See guardrails/CATALOG_POLICY.md.")
    }
    # else: read/list/describe/SELECT, or using it only as a read source, falls through and is allowed.
}

exit 0
