param(
    [string]$DatabaseName = "ai_quote_dev",
    [string]$DatabaseUser = "postgres",
    [string]$DatabaseHost = "127.0.0.1",
    [int]$DatabasePort = 5432,
    [int]$ApiPort = 8080
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

if (-not $env:PGPASSWORD) {
    $securePassword = Read-Host "Enter the PostgreSQL password" -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
}

$env:AI_QUOTE_DB_NAME = $DatabaseName
$env:AI_QUOTE_DB_USER = $DatabaseUser
$env:AI_QUOTE_DB_HOST = $DatabaseHost
$env:AI_QUOTE_DB_PORT = "$DatabasePort"
$env:AI_QUOTE_PORT = "$ApiPort"

if (-not $env:PSQL_PATH) {
    $psqlCommand = Get-Command psql -ErrorAction SilentlyContinue
    if ($psqlCommand) {
        $env:PSQL_PATH = $psqlCommand.Source
    }
    else {
        throw "psql was not found. Add PostgreSQL bin to PATH or set PSQL_PATH."
    }
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "Node.js was not found. Install Node.js 20 or newer and reopen PowerShell."
}

Write-Host "Starting the AI dual-quote API on http://127.0.0.1:$ApiPort" -ForegroundColor Cyan
& $nodeCommand.Source (Join-Path $projectRoot "api\server.mjs")
