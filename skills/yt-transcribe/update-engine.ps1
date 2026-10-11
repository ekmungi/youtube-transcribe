<#
.SYNOPSIS
    Updates the installed yt-transcribe command without leaving it broken on Windows.

.DESCRIPTION
    `uv tool upgrade` fetches the newest commit of the GitHub repository and the newest library
    versions that server/pyproject.toml allows. On Windows it cannot replace the launcher while any
    program from the tool is running. The failed attempt deletes yt-transcribe.exe, and a second plain
    upgrade then reports "Nothing to upgrade" while the command stays missing. This script therefore:
      1. stops with exit code 2 when a process is running from the tool or its launcher folder,
      2. upgrades the tool, or installs it when it is missing,
      3. checks that `yt-transcribe --version` answers, and reinstalls when it does not.

    Exit codes: 0 updated and working, 1 failed, 2 refused because the tool is in use.

    Run it from a terminal with:
      powershell -NoProfile -ExecutionPolicy Bypass -File update-engine.ps1
    (the bypass applies to this one process; Windows PowerShell blocks scripts by default.)

.PARAMETER Source
    Where uv installs the tool from. Defaults to the GitHub repository.

.PARAMETER ToolName
    Name of the uv tool. Defaults to yt-transcribe.
#>
[CmdletBinding()]
param(
    [string]$Source = 'git+https://github.com/ekmungi/youtube-transcribe.git#subdirectory=server',
    [string]$ToolName = 'yt-transcribe'
)

# Python version the engine is installed with; matches the install command in the README.
$script:EnginePython = '3.12'

<#
.SYNOPSIS  True when the uv command can be found.
#>
function Test-UvAvailable {
    return [bool](Get-Command uv -ErrorAction SilentlyContinue)
}

<#
.SYNOPSIS  Runs uv, showing its output live, and returns its exit code.
.PARAMETER UvArgs  Arguments for uv.
.NOTES
    This machine drops connections when uv downloads in parallel, so two downloads and a 60 second
    timeout are used unless the caller already set those variables. They are restored afterwards.
#>
function Invoke-Uv {
    param([Parameter(Mandatory)][string[]]$UvArgs)
    $defaults = @{ UV_CONCURRENT_DOWNLOADS = '2'; UV_HTTP_TIMEOUT = '60' }
    $saved = @{}
    foreach ($name in $defaults.Keys) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name)
        if (-not $saved[$name]) { [Environment]::SetEnvironmentVariable($name, $defaults[$name]) }
    }
    $ErrorActionPreference = 'Continue'
    try {
        & uv @UvArgs 2>&1 | ForEach-Object { Write-Host "$_" }
        return $LASTEXITCODE
    }
    finally {
        foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    }
}

<#
.SYNOPSIS  Runs uv and returns the first line it printed, trimmed.
.PARAMETER UvArgs  Arguments for uv.
#>
function Get-UvText {
    param([Parameter(Mandatory)][string[]]$UvArgs)
    $lines = @(& uv @UvArgs 2>$null)
    if ($lines.Count -eq 0) { return '' }
    return ("$($lines[0])").Trim()
}

<#
.SYNOPSIS  Asks uv where the tool and its launcher live.
.PARAMETER ToolName  Name of the uv tool.
.OUTPUTS   Object with ToolDir, BinDir, Launcher and Installed.
#>
function Get-ToolPaths {
    param([Parameter(Mandatory)][string]$ToolName)
    # GetFullPath turns the forward slashes that UV_TOOL_DIR may contain into backslashes.
    $toolsRoot = [IO.Path]::GetFullPath((Get-UvText -UvArgs @('tool', 'dir')))
    $binDir = [IO.Path]::GetFullPath((Get-UvText -UvArgs @('tool', 'dir', '--bin')))
    $toolDir = Join-Path $toolsRoot $ToolName
    return [pscustomobject]@{
        ToolDir   = $toolDir
        BinDir    = $binDir
        Launcher  = Join-Path $binDir "$ToolName.exe"
        Installed = (Test-Path -LiteralPath $toolDir -PathType Container)
    }
}

<#
.SYNOPSIS  Lists processes that would lock the tool: its own python.exe and its launchers.
.PARAMETER ToolDir   Folder holding the tool's private environment.
.PARAMETER BinDir    Folder holding the launcher executables.
.PARAMETER ToolName  Launchers are the files in BinDir whose name starts with this.
#>
function Get-RunningFromTool {
    param([string]$ToolDir, [string]$BinDir, [string]$ToolName)
    # The trailing separator keeps a sibling such as "yt-transcribe-old" from matching.
    $toolPrefix = $ToolDir.TrimEnd('\') + '\'
    $binFolder = $BinDir.TrimEnd('\')
    Get-CimInstance -ClassName Win32_Process | Where-Object {
        $path = $_.ExecutablePath
        if (-not $path) { return $false }
        if ($path.StartsWith($toolPrefix, [StringComparison]::OrdinalIgnoreCase)) { return $true }
        $sameFolder = [IO.Path]::GetDirectoryName($path) -ieq $binFolder
        return ($sameFolder -and ([IO.Path]::GetFileName($path) -like "$ToolName*.exe"))
    }
}

<#
.SYNOPSIS  True when the launcher exists and `--version` exits with 0.
.PARAMETER Launcher  Full path of the launcher executable.
#>
function Test-EngineLauncher {
    param([Parameter(Mandatory)][string]$Launcher)
    if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) { return $false }
    try {
        & $Launcher --version *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
}

<#
.SYNOPSIS  Returns the version the launcher reports, or $null when it cannot be read.
.PARAMETER Launcher  Full path of the launcher executable.
#>
function Get-EngineVersion {
    param([Parameter(Mandatory)][string]$Launcher)
    if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) { return $null }
    try {
        $text = (& $Launcher --version 2>&1) -join ' '
        if ($text -match 'version\s+(\S+)') { return $Matches[1] }
    }
    catch { }
    return $null
}

<#
.SYNOPSIS  The whole update: guard, upgrade or install, verify, reinstall if needed.
.PARAMETER Source    Where uv installs the tool from.
.PARAMETER ToolName  Name of the uv tool.
.OUTPUTS   Exit code: 0 updated and working, 1 failed, 2 refused because the tool is in use.
#>
function Invoke-EngineUpdate {
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$ToolName)

    if (-not (Test-UvAvailable)) {
        Write-Host '[update-engine] uv was not found on PATH. Install it first: https://docs.astral.sh/uv/'
        return 1
    }
    try { $paths = Get-ToolPaths -ToolName $ToolName }
    catch {
        Write-Host "[update-engine] Could not ask uv where its tools live: $($_.Exception.Message)"
        return 1
    }

    $busy = @(Get-RunningFromTool -ToolDir $paths.ToolDir -BinDir $paths.BinDir -ToolName $ToolName)
    if ($busy.Count -gt 0) {
        Write-Host "[update-engine] Not updating: $($busy.Count) process(es) are running from $ToolName, and Windows would leave it half-installed."
        foreach ($p in $busy) { Write-Host "    pid $($p.ProcessId)  $($p.Name)  $($p.ExecutablePath)" }
        Write-Host '[update-engine] Let them finish or close them, then run this again.'
        return 2
    }

    $before = Get-EngineVersion -Launcher $paths.Launcher
    # A blank would read as a typo in the messages below, so say "none" when no version is readable.
    $beforeText = if ($before) { $before } else { 'none' }
    if ($paths.Installed) {
        Write-Host "[update-engine] Upgrading $ToolName (now: $beforeText)..."
        $code = Invoke-Uv -UvArgs @('tool', 'upgrade', '--native-tls', $ToolName)
    }
    else {
        Write-Host "[update-engine] $ToolName is not installed; installing it..."
        $code = Invoke-Uv -UvArgs @('tool', 'install', '--native-tls', '--python', $script:EnginePython, $Source)
    }

    if (-not (Test-EngineLauncher -Launcher $paths.Launcher)) {
        Write-Host "[update-engine] $($paths.Launcher) does not answer --version; reinstalling..."
        [void](Invoke-Uv -UvArgs @('tool', 'install', '--reinstall', '--native-tls', '--python', $script:EnginePython, $Source))
        if (-not (Test-EngineLauncher -Launcher $paths.Launcher)) {
            Write-Host "[update-engine] FAILED: $($paths.Launcher) still does not answer --version."
            return 1
        }
    }
    elseif ($code -ne 0) {
        Write-Host "[update-engine] uv reported an error (exit code $code). The existing command still works, so nothing was reinstalled."
        return 1
    }

    $after = Get-EngineVersion -Launcher $paths.Launcher
    $afterText = if ($after) { $after } else { 'unknown' }
    Write-Host "[update-engine] Done. $ToolName version: $beforeText -> $afterText"
    return 0
}

# Dot-sourcing (as the tests do) loads the functions without running the update.
if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-EngineUpdate -Source $Source -ToolName $ToolName)
}
