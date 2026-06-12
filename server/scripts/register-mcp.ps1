# Register YT Transcribe MCP server with Claude Code.
# Writes the server entry into ~/.claude/.mcp.json mcpServers block.

param(
    [Parameter(Mandatory=$true)]
    [string]$ServerPath
)

$claudeConfigPath = Join-Path $env:USERPROFILE ".claude.json"

# Load existing config or start fresh
if (Test-Path $claudeConfigPath) {
    $config = Get-Content $claudeConfigPath -Raw | ConvertFrom-Json
} else {
    $config = [PSCustomObject]@{}
}

# Ensure mcpServers key exists
if (-not $config.PSObject.Properties["mcpServers"]) {
    $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
}

# Add yt-transcribe server entry
$serverEntry = [PSCustomObject]@{
    command = $ServerPath
    args    = @()
}

# Remove existing entry if present, then add
if ($config.mcpServers.PSObject.Properties["yt-transcribe"]) {
    $config.mcpServers.PSObject.Properties.Remove("yt-transcribe")
}
$config.mcpServers | Add-Member -NotePropertyName "yt-transcribe" -NotePropertyValue $serverEntry

# Write back
$config | ConvertTo-Json -Depth 10 | Set-Content $claudeConfigPath -Encoding UTF8

Write-Host "MCP server registered at: $ServerPath"
