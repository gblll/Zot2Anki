[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$AnkiPackages = "",
    [string]$Config = "",
    [string]$Wheelhouse = ""
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
try {
    if (-not $Python) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($py) { $Python = & $py.Source -3.13 -c "import sys; print(sys.executable)" }
        if (-not $Python) {
            $candidate = Get-Command python -ErrorAction SilentlyContinue
            if ($candidate) { $Python = $candidate.Source }
        }
    }
    if (-not $Python) { throw "Install Windows x64 Python 3.13 or provide -Python with its executable path." }
    & $Python -c "import sys,platform; assert sys.version_info[:2] == (3,13) and platform.machine().lower() in ('amd64','x86_64') and sys.platform == 'win32', 'Windows x64 Python 3.13 required'"
    if ($LASTEXITCODE -ne 0) { throw "Selected Python is incompatible." }
    $venv = Join-Path $repoRoot ".venv"
    if (-not (Test-Path -LiteralPath $venv)) {
        & $Python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Cannot create project .venv." }
    }
    $runtime = Join-Path $venv "Scripts\python.exe"
    & $runtime -c "import sys; assert sys.version_info[:2] == (3,13), 'Existing .venv is incompatible'"
    if ($LASTEXITCODE -ne 0) { throw "Existing .venv uses the wrong Python. Move it aside and run setup again." }
    $pipArguments = @("-m", "pip", "install", "--require-hashes", "--only-binary=:all:", "-r", (Join-Path $repoRoot "requirements.txt"))
    if ($Wheelhouse) { $pipArguments += @("--no-index", "--find-links", $Wheelhouse) }
    & $runtime @pipArguments
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation or hash verification failed." }
    $checkArguments = @((Join-Path $PSScriptRoot "sync_vocabulary.py"), "--check")
    if ($AnkiPackages) { $checkArguments += @("--anki-packages", $AnkiPackages) }
    if ($Config) { $checkArguments += @("--config", $Config) }
    & $runtime @checkArguments
    if ($LASTEXITCODE -ne 0) { throw "Anki backend or runtime check failed." }
    Write-Host "Setup complete. Configure config.local.json, then run Syne_Zot2Anki.cmd."
    exit 0
}
catch {
    Write-Host ("Setup failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 2
}
