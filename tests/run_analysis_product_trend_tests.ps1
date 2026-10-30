$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = [string]$env:AI_QUOTE_CLIENT_PYTHON
if ([string]::IsNullOrWhiteSpace($pythonExe)) { $pythonExe = 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe' }
if ([string]::IsNullOrWhiteSpace([string]$env:AI_QUOTE_V3_CORE_ROOT)) {
    $env:AI_QUOTE_V3_CORE_ROOT = Join-Path (Split-Path -Parent $repoRoot) 'AIQuoteDualSystem\_internal\v3_core'
}
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $repoRoot
try {
    & $pythonExe tests/run_quote_management_checks.py verify_analysis_product_trend.py verify_quote_analysis.py verify_quote_analysis_full_workflow.py verify_contract_status.py
    if ($LASTEXITCODE -ne 0) { throw 'Product classification/trend Qt regressions failed.' }
    # The actual HTTP fixture must run directly, outside the all-network-blocked runner.
    & $pythonExe tests/verify_analysis_product_trend_http.py
    if ($LASTEXITCODE -ne 0) { throw 'Actual API/Qt product classification regression failed.' }
} finally { Pop-Location }
