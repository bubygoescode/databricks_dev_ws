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
$disallowed = @('system', 'samples', 'gops_dev', 'sandbox_hackaton')

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

foreach ($catalog in $disallowed) {
    if ($cmdLower -match "\b$catalog\b") {
        $msg = "BLOCKED by project guardrail: catalog '$catalog' is out of scope for this project. " +
               "Claude is only authorized to read/write Unity Catalog data in '$allowedCatalog'. " +
               "This command references '$catalog' in what looks like a Databricks/SQL/Unity Catalog operation. " +
               "See guardrails/CATALOG_POLICY.md. If this catalog genuinely needs to be touched, ask the user to update it."

        $result = @{
            continue     = $false
            stopReason   = $msg
            systemMessage = $msg
            hookSpecificOutput = @{
                hookEventName            = 'PreToolUse'
                permissionDecision       = 'deny'
                permissionDecisionReason = $msg
            }
        } | ConvertTo-Json -Depth 5 -Compress

        Write-Output $result
        exit 0
    }
}

exit 0
