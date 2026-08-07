$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python 3.11 or 3.12 was not found."
    }
    & $pythonCommand.Source -m venv (Join-Path $projectRoot ".venv")
    & $venvPython -m pip install -r (Join-Path $projectRoot "desktop_client\requirements.txt")
}

& $venvPython (Join-Path $projectRoot "desktop_client\main.py")
