# Unregister YT Transcribe MCP server from Claude Code.
# Removes the server entry from ~/.claude/.mcp.json mcpServers block.

$claudeConfigPath = Join-Path $env:USERPROFILE ".claude.json"

if (-not (Test-Path $claudeConfigPath)) {
    exit 0
}

$config = Get-Content $claudeConfigPath -Raw | ConvertFrom-Json

if (-not $config.PSObject.Properties["mcpServers"]) {
    exit 0
}

if ($config.mcpServers.PSObject.Properties["yt-transcribe"]) {
    $config.mcpServers.PSObject.Properties.Remove("yt-transcribe")
    $config | ConvertTo-Json -Depth 10 | Set-Content $claudeConfigPath -Encoding UTF8
    Write-Host "MCP server unregistered."
}
