[CmdletBinding()]
param(
    [string]$Config = "",
    [string]$Database = "",
    [string]$NoteTitle = "",
    [string]$OutputDir = "",
    [string]$AnkiProfile = "",
    [string]$AnkiRoot = "",
    [string]$Collection = "",
    [string]$AnkiPackages = "",
    [string]$AnkiExe = "",
    [switch]$NoOnline,
    [switch]$Check,
    [switch]$DryRun,
    [switch]$AllowLargeRemoval,
    [switch]$RefreshExamples,
    [switch]$SkipInvalidSources,
    [string]$Recover = "",
    [switch]$NoOpenAnki
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function ConvertTo-WindowsCommandLine {
    param([string[]]$Arguments)

    # Windows PowerShell 5.1 has no ProcessStartInfo.ArgumentList. For the
    # Windows argv parser, double backslashes before quotes and at the end of
    # a quoted argument, then escape each literal quote with one backslash.
    ($Arguments | ForEach-Object {
        $value = [regex]::Replace([string]$_, '(\\*)"', '$1$1\"')
        $value = [regex]::Replace($value, '(\\+)$', '$1$1')
        '"' + $value + '"'
    }) -join ' '
}

function Start-RedirectedProcess {
    param([string]$FilePath, [string[]]$Arguments)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.WorkingDirectory = (Get-Location).ProviderPath
    $psi.Arguments = ConvertTo-WindowsCommandLine -Arguments $Arguments
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    return $process
}

function Disable-ConsoleQuickEdit {
    try {
        if ($null -eq ("Zot2AnkiConsoleMode" -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class Zot2AnkiConsoleMode
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
}
'@
        }

        $handle = [Zot2AnkiConsoleMode]::GetStdHandle(-10)
        [uint32]$originalMode = 0
        if (-not [Zot2AnkiConsoleMode]::GetConsoleMode($handle, [ref]$originalMode)) {
            return $null
        }

        # ENABLE_EXTENDED_FLAGS must be set when ENABLE_QUICK_EDIT_MODE is changed.
        $newMode = $originalMode -bor 0x0080
        if (($newMode -band 0x0040) -ne 0) {
            $newMode = $newMode -bxor 0x0040
        }
        if (-not [Zot2AnkiConsoleMode]::SetConsoleMode($handle, [uint32]$newMode)) {
            return $null
        }

        return [PSCustomObject]@{
            Handle = $handle
            Mode = $originalMode
        }
    }
    catch {
        # Redirection still prevents the large Python output from blocking even
        # when the host does not expose a traditional Windows console handle.
        return $null
    }
}

function Restore-ConsoleMode {
    param($State)

    if ($null -ne $State) {
        try {
            [void][Zot2AnkiConsoleMode]::SetConsoleMode(
                [IntPtr]$State.Handle,
                [uint32]$State.Mode
            )
        }
        catch {
            # The console is about to close (or pause on failure), so restoration
            # failure is not allowed to mask the synchronization result.
        }
    }
}

$consoleModeState = Disable-ConsoleQuickEdit
$scriptExitCode = 1
$process = $null
try {
    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
    $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Project .venv is missing. Run scripts/setup.ps1 first."
    }
    $arguments = @((Join-Path $PSScriptRoot "sync_vocabulary.py"))
    $overrides = @{
        "config" = $Config; "database" = $Database; "note-title" = $NoteTitle
        "output-dir" = $OutputDir; "anki-profile" = $AnkiProfile; "anki-root" = $AnkiRoot
        "collection" = $Collection; "anki-packages" = $AnkiPackages; "anki-exe" = $AnkiExe
        "recover" = $Recover
    }
    foreach ($name in $overrides.Keys) {
        if ($overrides[$name]) { $arguments += @("--$name", $overrides[$name]) }
    }
    foreach ($flag in @(@("no-online", $NoOnline), @("check", $Check), @("dry-run", $DryRun),
                       @("allow-large-removal", $AllowLargeRemoval), @("refresh-examples", $RefreshExamples),
                       @("skip-invalid-sources", $SkipInvalidSources))) {
        if ($flag[1]) { $arguments += "--$($flag[0])" }
    }
    # Python emits a short status and the journal path, not private report contents.
    # Run Python asynchronously so the console stays alive and informative while
    # a large library is being synchronized.
    $process = Start-RedirectedProcess -FilePath $python -Arguments $arguments
    # Drain both streams concurrently so neither redirected pipe can fill and
    # block a long-running synchronization.
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $started = Get-Date
    $frames = @('|', '/', '-', '\')
    $activity = if ($Check) { 'Checking environment...' }
                elseif ($Recover) { 'Recovering outputs...' }
                elseif ($DryRun) { 'Planning synchronization...' }
                else { 'Synchronizing...' }
    $frameIndex = 0
    while (-not $process.HasExited) {
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        Write-Host ("`r  [{0}] {1} ({2}s)   " -f $frames[$frameIndex % $frames.Count], $activity, $elapsed) -NoNewline
        $frameIndex++
        Start-Sleep -Milliseconds 250
    }
    $process.WaitForExit()
    $stdout = @($stdoutTask.GetAwaiter().GetResult() -split "\r?\n" | Where-Object { $_ -ne "" })
    $stderr = @($stderrTask.GetAwaiter().GetResult() -split "\r?\n" | Where-Object { $_ -ne "" })
    Write-Host "`r$(' ' * 90)`r" -NoNewline
    $output = @($stdout)
    $stderr | ForEach-Object { $output += $_ }
    $scriptExitCode = $process.ExitCode
    $output | ForEach-Object { Write-Host $_ }
    if ($scriptExitCode -eq 0 -and -not ($Check -or $DryRun -or $Recover)) {
        $line = $output | Where-Object { $_ -like "Sync complete. Report: *" } | Select-Object -Last 1
        if (-not $line) { throw "Sync did not return a completed report." }
        $reportPath = $line.Substring("Sync complete. Report: ".Length)
        if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "Report is missing." }
        $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($report.stage -ne "complete" -or -not $report.committed) { throw "Report does not confirm commit completion." }
        Write-Host "Updated collection: $($report.collection)"
        if ($report.profile -and -not $NoOpenAnki) {
            $configArguments = @((Join-Path $PSScriptRoot "local_config.py"))
            foreach ($name in $overrides.Keys) {
                if ($name -ne "recover" -and $overrides[$name]) { $configArguments += @("--$name", $overrides[$name]) }
            }
            $configProcess = Start-RedirectedProcess -FilePath $python -Arguments $configArguments
            try {
                $configStdoutTask = $configProcess.StandardOutput.ReadToEndAsync()
                $configStderrTask = $configProcess.StandardError.ReadToEndAsync()
                $configProcess.WaitForExit()
                $configStdout = $configStdoutTask.GetAwaiter().GetResult()
                $configStderr = $configStderrTask.GetAwaiter().GetResult()
                if ($configProcess.ExitCode -ne 0) { throw "Cannot resolve Anki launch settings. $configStderr" }
                $settings = $configStdout | ConvertFrom-Json
            }
            finally {
                $configProcess.Dispose()
            }
            $ankiExe = $settings.anki_exe
            if (Test-Path -LiteralPath $ankiExe -PathType Leaf) {
                $ankiArguments = ConvertTo-WindowsCommandLine -Arguments @("-b", $settings.anki_root, "-p", $report.profile)
                Start-Process -FilePath $ankiExe -ArgumentList $ankiArguments
            }
        }
    }
}
catch {
    Write-Host ("Zot2Anki failed: " + $_.Exception.Message) -ForegroundColor Red
    $scriptExitCode = 2
}
finally {
    if ($null -ne $process) { $process.Dispose() }
    Restore-ConsoleMode $consoleModeState
}
exit $scriptExitCode
