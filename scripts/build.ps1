[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$manifestPath = Join-Path $projectRoot "manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$version = [string]$manifest.version

$distRoot = Join-Path $projectRoot "dist"
if (-not (Test-Path -LiteralPath $distRoot)) {
    New-Item -ItemType Directory -Path $distRoot | Out-Null
}
$distRoot = (Resolve-Path -LiteralPath $distRoot).Path
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $distRoot "zotero2anki-$version.xpi"))
$distPrefix = $distRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $outputPath.StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to write outside the dist directory: $outputPath"
}

if (Test-Path -LiteralPath $outputPath) {
    Remove-Item -LiteralPath $outputPath -Force
}

$rootFiles = @(
    "manifest.json",
    "bootstrap.js",
    "prefs.js",
    "core.js",
    "zotero2anki.js"
)
$files = foreach ($relativePath in $rootFiles) {
    Get-Item -LiteralPath (Join-Path $projectRoot $relativePath)
}
$files += Get-ChildItem -LiteralPath (Join-Path $projectRoot "preferences") -File -Recurse
$files += Get-ChildItem -LiteralPath (Join-Path $projectRoot "locale") -File -Recurse

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$stream = [System.IO.File]::Open(
    $outputPath,
    [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::None
)
$archive = [System.IO.Compression.ZipArchive]::new(
    $stream,
    [System.IO.Compression.ZipArchiveMode]::Create,
    $false
)

try {
    foreach ($file in $files) {
        $entryName = $file.FullName.Substring($projectRoot.Length + 1).Replace("\", "/")
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
    $stream.Dispose()
}

$readArchive = [System.IO.Compression.ZipFile]::OpenRead($outputPath)
try {
    $entryNames = @($readArchive.Entries | ForEach-Object FullName)
    foreach ($requiredEntry in @("manifest.json", "bootstrap.js", "core.js", "zotero2anki.js")) {
        if ($entryNames -notcontains $requiredEntry) {
            throw "Package validation failed: missing $requiredEntry"
        }
    }
    if ($entryNames | Where-Object { $_ -match "^[^/]+/manifest\.json$" }) {
        throw "Package validation failed: manifest.json is nested instead of being at the archive root"
    }
}
finally {
    $readArchive.Dispose()
}

Write-Output "Built and validated: $outputPath"
