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
    [switch]$NoOnline
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

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
$logPath = $null

try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    if (-not $Config) { $Config = Join-Path $repoRoot "config.local.json" }
    $Config = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Config)
    $python = Get-Command python -ErrorAction Stop
    $configArguments = @((Join-Path $PSScriptRoot "local_config.py"), "--config", $Config)
    $overrides = @{
        "database" = $Database; "note-title" = $NoteTitle; "output-dir" = $OutputDir
        "anki-profile" = $AnkiProfile; "anki-root" = $AnkiRoot; "collection" = $Collection
        "anki-packages" = $AnkiPackages; "anki-exe" = $AnkiExe
    }
    foreach ($key in $overrides.Keys) {
        if ($overrides[$key]) { $configArguments += @("--$key", $overrides[$key]) }
    }
    if ($NoOnline) { $configArguments += "--no-online" }
    $configJson = & $python.Source @configArguments
    if ($LASTEXITCODE -ne 0) { throw "Invalid local configuration. See the configuration error above." }
    $settings = ($configJson -join "`n") | ConvertFrom-Json
    $Database = $settings.database
    $NoteTitle = $settings.note_title
    $outputRoot = $settings.output_dir
    $collection = $settings.collection
    $ankiPackages = $settings.anki_packages
    $ankiExe = $settings.anki_exe
    $runId = Get-Date -Format "yyyyMMdd-HHmmss"
    $logDirectory = Join-Path $outputRoot "logs"
    $logPath = Join-Path $logDirectory "sync-$runId.log"
    $reportPath = Join-Path $outputRoot "zot2anki-sync-$runId.json"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

    Write-Host "[1/3] Checking applications, paths, and dependencies..."

    $running = Get-Process -Name anki,zotero -ErrorAction SilentlyContinue
    if ($running) {
        $names = ($running.ProcessName | Sort-Object -Unique) -join ", "
        throw "Detected running application(s): $names. Close Zotero and Anki manually, wait a few seconds, and retry. This script never terminates them automatically."
    }
    $env:ZOT2ANKI_APPS_CLOSED_CHECKED = "1"

    if (-not (Test-Path -LiteralPath $Database)) { throw "Zotero database not found: $Database" }
    if (-not (Test-Path -LiteralPath $collection)) { throw "Anki collection not found: $collection" }
    if (-not (Test-Path -LiteralPath $ankiPackages)) { throw "Anki Python packages not found: $ankiPackages" }
    if (-not (Test-Path -LiteralPath $ankiExe)) { throw "Anki executable not found: $ankiExe" }

    & $python.Source -c "import pymupdf" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyMuPDF is missing. Run: python -m pip install -r requirements.txt"
    }

    $arguments = @(
        (Join-Path $PSScriptRoot "sync_vocabulary.py"),
        "--config", $Config,
        "--database", $Database,
        "--note-title", $NoteTitle,
        "--output-dir", $outputRoot,
        "--collection", $collection,
        "--anki-packages", $ankiPackages,
        "--timestamp", $runId
    )
    if ($settings.no_online) { $arguments += "--no-online" }

    Write-Host "[2/3] Synchronizing the configured Anki collection. This may take several minutes..."
    Write-Host "      Detailed log: $logPath"

    Push-Location $repoRoot
    try {
        & $python.Source @arguments *> $logPath
        $pythonExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($pythonExitCode -ne 0) {
        throw "Sync failed with exit code $pythonExitCode."
    }
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw "Sync process exited successfully but did not create its report: $reportPath"
    }
    try {
        $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Sync report is not valid JSON: $reportPath"
    }
    if ([string]$report.timestamp -ne $runId) {
        throw "Sync report timestamp does not match this run: $reportPath"
    }

    Write-Host (
        "[3/3] Sync complete: added {0}, updated {1}, total {2}. Reopening Anki..." -f
        $report.sync.added,
        $report.sync.updated,
        $report.final.cards
    )
    Start-Process -FilePath $ankiExe
    $scriptExitCode = 0
}
catch {
    $message = $_.Exception.Message
    if ($null -ne $logPath) {
        try {
            "PowerShell failure: $message" | Out-File -LiteralPath $logPath -Append
        }
        catch {
            # Continue showing the original failure even if the log is unwritable.
        }
    }

    Write-Host ""
    Write-Host "Zot2Anki sync failed: $message" -ForegroundColor Red
    if ($null -ne $logPath) {
        Write-Host "Detailed log: $logPath"
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            Write-Host ""
            Write-Host "Last log lines:"
            Get-Content -LiteralPath $logPath -Tail 20 -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Restore-ConsoleMode $consoleModeState
}

exit $scriptExitCode
