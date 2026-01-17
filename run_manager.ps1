param(
    [string]$Root = (Get-Location).Path,
    [int]$Port = 8022,
    [string]$BindHost = "127.0.0.1",
    [switch]$ScanOnly,
    [switch]$Backup
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path $Root).Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$managerScript = Join-Path $repoRoot "tools\f22_data_manager.py"

if (-not (Test-Path $managerScript)) {
    throw "Cannot find manager script: $managerScript"
}

if (-not (Test-Path $venvPython)) {
    throw "Cannot find venv python at: $venvPython`nCreate it first (python -m venv .venv) and install deps if needed."
}

$argsList = @(
    $managerScript,
    $repoRoot,
    "--port", $Port,
    "--host", $BindHost
)

if ($ScanOnly) { $argsList += "--scan-only" }
if ($Backup)   { $argsList += "--backup" }

& $venvPython @argsList
