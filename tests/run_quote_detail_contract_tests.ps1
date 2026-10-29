$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = [string]$env:AI_QUOTE_CLIENT_PYTHON
if ([string]::IsNullOrWhiteSpace($pythonExe)) { $pythonExe = 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw 'Set AI_QUOTE_CLIENT_PYTHON to the isolated development Python.' }
if ([string]::IsNullOrWhiteSpace([string]$env:AI_QUOTE_V3_CORE_ROOT)) {
    $env:AI_QUOTE_V3_CORE_ROOT = Join-Path (Split-Path -Parent $repoRoot) 'AIQuoteDualSystem\_internal\v3_core'
}
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $repoRoot
try {
    & $pythonExe tests/verify_quote_detail_contract.py
    if ($LASTEXITCODE -ne 0) { throw 'Quotation detail contract regression failed.' }
} finally { Pop-Location }
