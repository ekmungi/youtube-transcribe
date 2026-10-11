# Pester 3 tests for update-engine.ps1. They cover the guard against running processes, the launcher
# check, and the decisions between upgrade, reinstall and fresh install. uv and the process list are
# faked at their thin wrappers, so nothing here touches a real install.
# Run: powershell -NoProfile -Command "Invoke-Pester -Path skills/yt-transcribe -EnableExit"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'update-engine.ps1')

function New-FakeProcess($id, $name, $path) {
    [pscustomobject]@{ ProcessId = $id; Name = $name; ExecutablePath = $path }
}

Describe 'Get-RunningFromTool' {
    $toolDir = 'C:\uv\tools\yt-transcribe'
    $binDir = 'C:\bin'

    It 'returns the python.exe that lives inside the tool folder' {
        Mock Get-CimInstance { @(New-FakeProcess 10 'python.exe' 'C:\uv\tools\yt-transcribe\Scripts\python.exe') }
        $found = @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe')
        $found.Count | Should Be 1
        $found[0].ProcessId | Should Be 10
    }

    It 'returns a launcher from the bin folder whose name starts with the tool name' {
        Mock Get-CimInstance { @(
            (New-FakeProcess 11 'yt-transcribe.exe' 'C:\bin\yt-transcribe.exe'),
            (New-FakeProcess 12 'yt-transcribe-extra.exe' 'C:\bin\yt-transcribe-extra.exe')) }
        @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe').Count | Should Be 2
    }

    It 'ignores unrelated processes and the launchers of other tools' {
        Mock Get-CimInstance { @(
            (New-FakeProcess 20 'notepad.exe' 'C:\Windows\notepad.exe'),
            (New-FakeProcess 21 'python.exe' 'C:\uv\tools\other\Scripts\python.exe'),
            (New-FakeProcess 22 'ruff.exe' 'C:\bin\ruff.exe')) }
        @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe').Count | Should Be 0
    }

    It 'does not treat a sibling folder that shares the tool name prefix as the tool' {
        Mock Get-CimInstance { @(New-FakeProcess 30 'python.exe' 'C:\uv\tools\yt-transcribe-old\Scripts\python.exe') }
        @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe').Count | Should Be 0
    }

    It 'matches paths regardless of letter case' {
        Mock Get-CimInstance { @(New-FakeProcess 40 'PYTHON.EXE' 'c:\UV\Tools\YT-Transcribe\scripts\python.exe') }
        @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe').Count | Should Be 1
    }

    It 'skips processes that report no executable path' {
        Mock Get-CimInstance { @(New-FakeProcess 0 'System Idle Process' $null) }
        @(Get-RunningFromTool -ToolDir $toolDir -BinDir $binDir -ToolName 'yt-transcribe').Count | Should Be 0
    }
}

Describe 'Test-UvAvailable' {
    It 'is true when uv resolves to a command' {
        Mock Get-Command { [pscustomobject]@{ Name = 'uv' } }
        Test-UvAvailable | Should Be $true
    }
    It 'is false when uv cannot be found' {
        Mock Get-Command { $null }
        Test-UvAvailable | Should Be $false
    }
}

Describe 'Test-EngineLauncher and Get-EngineVersion' {
    $okLauncher = Join-Path $TestDrive 'ok.cmd'
    $badLauncher = Join-Path $TestDrive 'bad.cmd'
    Set-Content -Path $okLauncher -Value "@echo yt-transcribe, version 1.2.3`r`n@exit /b 0"
    Set-Content -Path $badLauncher -Value "@echo boom`r`n@exit /b 1"

    It 'accepts a launcher that answers --version successfully' {
        Test-EngineLauncher -Launcher $okLauncher | Should Be $true
    }
    It 'rejects a launcher file that does not exist' {
        Test-EngineLauncher -Launcher (Join-Path $TestDrive 'missing.exe') | Should Be $false
    }
    It 'rejects a launcher that exits with an error' {
        Test-EngineLauncher -Launcher $badLauncher | Should Be $false
    }
    It 'reads the version number from the launcher output' {
        Get-EngineVersion -Launcher $okLauncher | Should Be '1.2.3'
    }
    It 'returns nothing when the launcher is missing' {
        Get-EngineVersion -Launcher (Join-Path $TestDrive 'missing.exe') | Should BeNullOrEmpty
    }
}

Describe 'Invoke-Uv and Get-UvText' {
    BeforeEach {
        Mock Write-Host { }
        $global:UvSeenArgs = $null
        $global:UvSeenDownloads = 'unset'
        $global:UvSeenTimeout = 'unset'
        $script:savedDownloads = $env:UV_CONCURRENT_DOWNLOADS
        $script:savedTimeout = $env:UV_HTTP_TIMEOUT
        Remove-Item Env:UV_CONCURRENT_DOWNLOADS -ErrorAction SilentlyContinue
        Remove-Item Env:UV_HTTP_TIMEOUT -ErrorAction SilentlyContinue
        function uv {
            $global:UvSeenArgs = $args
            $global:UvSeenDownloads = $env:UV_CONCURRENT_DOWNLOADS
            $global:UvSeenTimeout = $env:UV_HTTP_TIMEOUT
            'C:\uv\tools  '
            $global:LASTEXITCODE = 7
        }
    }
    AfterEach {
        Remove-Item Function:\uv -ErrorAction SilentlyContinue
        if ($null -ne $script:savedDownloads) { $env:UV_CONCURRENT_DOWNLOADS = $script:savedDownloads }
        if ($null -ne $script:savedTimeout) { $env:UV_HTTP_TIMEOUT = $script:savedTimeout }
    }

    It 'Invoke-Uv passes the arguments to uv and returns its exit code' {
        $code = Invoke-Uv -UvArgs @('tool', 'upgrade', 'yt-transcribe')
        $code | Should Be 7
        ($global:UvSeenArgs -join ' ') | Should Be 'tool upgrade yt-transcribe'
    }
    It 'Invoke-Uv lowers download concurrency while uv runs and restores the environment afterwards' {
        Invoke-Uv -UvArgs @('tool', 'dir') | Out-Null
        $global:UvSeenDownloads | Should Be '2'
        $global:UvSeenTimeout | Should Be '60'
        $env:UV_CONCURRENT_DOWNLOADS | Should BeNullOrEmpty
        $env:UV_HTTP_TIMEOUT | Should BeNullOrEmpty
    }
    It 'Invoke-Uv keeps a download setting the user already chose' {
        $env:UV_CONCURRENT_DOWNLOADS = '9'
        Invoke-Uv -UvArgs @('tool', 'dir') | Out-Null
        $global:UvSeenDownloads | Should Be '9'
        $env:UV_CONCURRENT_DOWNLOADS | Should Be '9'
    }
    It 'Get-UvText returns the trimmed text uv printed' {
        Get-UvText -UvArgs @('tool', 'dir') | Should Be 'C:\uv\tools'
    }
}

Describe 'Get-ToolPaths' {
    It 'derives the tool folder, launcher and installed flag from uv' {
        $tools = Join-Path $TestDrive 'tools'
        $bin = Join-Path $TestDrive 'bin'
        New-Item -ItemType Directory -Path (Join-Path $tools 'yt-transcribe') -Force | Out-Null
        Mock Get-UvText { if ($UvArgs -contains '--bin') { $bin } else { $tools } }
        $paths = Get-ToolPaths -ToolName 'yt-transcribe'
        $paths.ToolDir | Should Be (Join-Path $tools 'yt-transcribe')
        $paths.BinDir | Should Be $bin
        $paths.Launcher | Should Be (Join-Path $bin 'yt-transcribe.exe')
        $paths.Installed | Should Be $true
    }
    It 'reports not installed when the tool folder does not exist' {
        $tools = Join-Path $TestDrive 'empty-tools'
        Mock Get-UvText { if ($UvArgs -contains '--bin') { 'C:\bin' } else { $tools } }
        (Get-ToolPaths -ToolName 'yt-transcribe').Installed | Should Be $false
    }
    It 'turns forward slashes from uv into backslashes' {
        Mock Get-UvText { if ($UvArgs -contains '--bin') { 'C:/some/bin' } else { 'C:/some/tools' } }
        $paths = Get-ToolPaths -ToolName 'yt-transcribe'
        $paths.BinDir | Should Be 'C:\some\bin'
        $paths.ToolDir | Should Be 'C:\some\tools\yt-transcribe'
    }
}

Describe 'Invoke-EngineUpdate' {
    $source = 'git+https://example.invalid/repo.git#subdirectory=server'
    BeforeEach {
        $script:launcherChecks = 0
        Mock Write-Host { }
        Mock Test-UvAvailable { $true }
        Mock Get-ToolPaths { [pscustomobject]@{ ToolDir = 'C:\t\yt-transcribe'; BinDir = 'C:\bin'
                                                  Launcher = 'C:\bin\yt-transcribe.exe'; Installed = $true } }
        Mock Get-RunningFromTool { @() }
        Mock Get-EngineVersion { '1.0.0' }
        Mock Test-EngineLauncher { $true }
        Mock Invoke-Uv { 0 }
    }

    It 'returns 1 and runs nothing when uv is not installed' {
        Mock Test-UvAvailable { $false }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 1
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 0
    }

    It 'refuses with exit code 2 while a process runs from the tool, and leaves the install alone' {
        Mock Get-RunningFromTool { @(New-FakeProcess 77 'python.exe' 'C:\t\yt-transcribe\Scripts\python.exe') }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 2
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 0
    }

    It 'names the blocking process in its message' {
        Mock Get-RunningFromTool { @(New-FakeProcess 77 'python.exe' 'C:\t\yt-transcribe\Scripts\python.exe') }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Out-Null
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*77*' }
    }

    It 'upgrades once with native TLS and returns 0 when the launcher still works' {
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 0
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 1 -ParameterFilter {
            ($UvArgs -join ' ') -eq 'tool upgrade --native-tls yt-transcribe' }
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 0 -ParameterFilter { $UvArgs -contains '--reinstall' }
    }

    It 'reinstalls when the upgrade succeeded but the launcher is gone, and returns 0 once it works' {
        Mock Test-EngineLauncher { $script:launcherChecks++; return ($script:launcherChecks -gt 1) }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 0
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 1 -ParameterFilter {
            ($UvArgs -join ' ') -eq "tool install --reinstall --native-tls --python 3.12 $source" }
    }

    It 'reinstalls after a failed upgrade' {
        Mock Invoke-Uv { if ($UvArgs -contains 'upgrade') { 1 } else { 0 } }
        Mock Test-EngineLauncher { $script:launcherChecks++; return ($script:launcherChecks -gt 1) }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 0
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 1 -ParameterFilter { $UvArgs -contains '--reinstall' }
    }

    It 'returns 1 when the launcher is still broken after the reinstall' {
        Mock Test-EngineLauncher { $false }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 1
    }

    It 'returns 1 without reinstalling when the upgrade failed but the command still works' {
        Mock Invoke-Uv { 1 }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 1
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 0 -ParameterFilter { $UvArgs -contains '--reinstall' }
    }

    It 'returns 1 and runs nothing when uv cannot say where its tools live' {
        Mock Get-ToolPaths { throw 'uv tool dir failed' }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 1
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 0
    }

    It 'installs fresh, without --reinstall, when the tool is not installed yet' {
        Mock Get-ToolPaths { [pscustomobject]@{ ToolDir = 'C:\t\yt-transcribe'; BinDir = 'C:\bin'
                                                  Launcher = 'C:\bin\yt-transcribe.exe'; Installed = $false } }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Should Be 0
        Assert-MockCalled Invoke-Uv -Scope It -Exactly 1 -ParameterFilter {
            ($UvArgs -join ' ') -eq "tool install --native-tls --python 3.12 $source" }
    }

    It 'says "none" instead of leaving a blank when no version could be read before the update' {
        $script:versionReads = 0
        Mock Get-EngineVersion { $script:versionReads++; if ($script:versionReads -eq 1) { $null } else { '1.1.0' } }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Out-Null
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*none -> 1.1.0*' }
    }

    It 'prints the version before and after' {
        $script:versionReads = 0
        Mock Get-EngineVersion { $script:versionReads++; if ($script:versionReads -eq 1) { '1.0.0' } else { '1.1.0' } }
        Invoke-EngineUpdate -Source $source -ToolName 'yt-transcribe' | Out-Null
        Assert-MockCalled Write-Host -Scope It -ParameterFilter { "$Object" -like '*1.0.0*' -and "$Object" -like '*1.1.0*' }
    }
}
