$ErrorActionPreference = "Stop"

$configuredPython = [string]$env:AI_QUOTE_CLIENT_PYTHON
$pythonCandidates = @(
    $configuredPython,
    "G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe"
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$pythonExe = $pythonCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $pythonExe) {
    throw "Python 3.12 x64 client environment was not found. Set AI_QUOTE_CLIENT_PYTHON to its python.exe path."
}

& $pythonExe -c "import struct,sys; assert sys.version_info[:2] == (3, 12), sys.version; assert struct.calcsize('P') * 8 == 64, 'Python must be 64-bit'; import PySide6"
if ($LASTEXITCODE -ne 0) {
    throw "Client tests require Python 3.12 x64 with PySide6: $pythonExe"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$defaultCoreRoot = Join-Path $workspaceRoot "AIQuoteDualSystem\_internal\v3_core"
if ([string]::IsNullOrWhiteSpace([string]$env:AI_QUOTE_V3_CORE_ROOT)) {
    $env:AI_QUOTE_V3_CORE_ROOT = $defaultCoreRoot
}
foreach ($requiredCoreFile in @("main.raw", "original.pyz")) {
    $requiredCorePath = Join-Path $env:AI_QUOTE_V3_CORE_ROOT $requiredCoreFile
    if (-not (Test-Path -LiteralPath $requiredCorePath -PathType Leaf)) {
        throw "Client runtime core is incomplete: $requiredCorePath"
    }
}

$testFiles = @(
    "tests/verify_quote_defaults.py",
    "tests/verify_attachment_size_rules.py",
    "tests/verify_v3_program_rules.py",
    "tests/verify_generated_formula_migration.py",
    "tests/verify_v3_layout_refresh.py"
)
foreach ($testFile in $testFiles) {
    & $pythonExe $testFile
    if ($LASTEXITCODE -ne 0) {
        throw "Client test failed: $testFile"
    }
}
