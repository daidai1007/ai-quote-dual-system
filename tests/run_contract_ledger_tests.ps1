$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$pythonExe = [string]$env:AI_QUOTE_CLIENT_PYTHON
if ([string]::IsNullOrWhiteSpace($pythonExe)) {
    $pythonExe = 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Set AI_QUOTE_CLIENT_PYTHON to the development Python with PySide6.'
}
& $pythonExe -c 'import PySide6, xlrd, xlwt'
if ($LASTEXITCODE -ne 0) {
    throw 'Install tests/requirements-contract-ledger.txt into the isolated test environment first.'
}
if ([string]::IsNullOrWhiteSpace([string]$env:AI_QUOTE_V3_CORE_ROOT)) {
    $env:AI_QUOTE_V3_CORE_ROOT = Join-Path $workspaceRoot 'AIQuoteDualSystem\_internal\v3_core'
}
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
$tests = @('verify_contract_ledger_reader.py','verify_contract_ledger_state.py','verify_contract_ledger_ui.py')
Push-Location $repoRoot
try {
    foreach ($test in $tests) {
        & $pythonExe (Join-Path $PSScriptRoot $test)
        if ($LASTEXITCODE -ne 0) { throw "Ledger test failed: $test" }
    }
} finally { Pop-Location }
