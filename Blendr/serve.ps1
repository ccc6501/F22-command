# Starts a tiny static file server for the POC viewer.
# Run: Right-click -> Run with PowerShell, or from a terminal: .\serve.ps1

$ErrorActionPreference = 'Stop'

$port = 8000
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "Serving this folder:" -ForegroundColor Cyan
Write-Host "  $here" -ForegroundColor Cyan
Write-Host "" 
Write-Host "Open in your browser:" -ForegroundColor Green
Write-Host "  http://localhost:$port/poc_touch.html" -ForegroundColor Green
Write-Host "" 
Write-Host "(Tip) Don't use file:// — the GLB won't load." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host "" 

python -m http.server $port
