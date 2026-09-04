[CmdletBinding()]
param(
    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop"),
    [string]$AnkiExe = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $repoRoot "Syne_Zot2Anki.cmd"
$configPath = Join-Path $repoRoot "config.local.json"
if (-not $AnkiExe -and (Test-Path -LiteralPath $configPath)) {
    $settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.anki_exe) {
        $AnkiExe = [Environment]::ExpandEnvironmentVariables($settings.anki_exe)
        if ($AnkiExe.StartsWith("~/") -or $AnkiExe.StartsWith("~\")) {
            $AnkiExe = Join-Path ([Environment]::GetFolderPath("UserProfile")) $AnkiExe.Substring(2)
        }
        if (-not [IO.Path]::IsPathRooted($AnkiExe)) { $AnkiExe = Join-Path $repoRoot $AnkiExe }
    }
}
if (-not $AnkiExe) { $AnkiExe = Join-Path $env:LOCALAPPDATA "Programs\Anki\Anki.exe" }
$shortcutName = "Syne_Zot2Anki"
$shortcutPath = Join-Path $DesktopPath ($shortcutName + ".lnk")

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw "Desktop directory not found: $DesktopPath"
}
if (-not (Test-Path -LiteralPath $ankiExe)) {
    throw "Anki executable not found: $ankiExe"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $repoRoot
$shortcut.IconLocation = "$ankiExe,0"
$shortcut.Description = "Synchronize the configured Zotero vocabulary note to Anki"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Output $shortcutPath
