param([Parameter(Mandatory=$true)][string]$Entry, [Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = 'Stop'
$taskRunId = [Guid]::NewGuid().ToString('N')
$taskProfile = Join-Path (Split-Path -Parent $PSScriptRoot) "outputs\startup-smoke-$Version-$taskRunId"
New-Item -ItemType Directory -Path $taskProfile -Force | Out-Null
$taskPreviousProfile = $env:LOCALAPPDATA
$taskPreviousQt = $env:QT_QPA_PLATFORM
$taskPreviousTemp = $env:TEMP
$taskPreviousTmp = $env:TMP
$taskProcess = $null
try {
    $env:LOCALAPPDATA = $taskProfile
    $env:TEMP = $taskProfile
    $env:TMP = $taskProfile
    $env:QT_QPA_PLATFORM = 'offscreen'
    $taskProcess = Start-Process -FilePath $Entry -WorkingDirectory (Split-Path -Parent $Entry) -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 12
    $taskProcess.Refresh()
    if ($taskProcess.HasExited) { throw "Client exited during startup: $($taskProcess.ExitCode)" }
    $taskLog = Join-Path $taskProfile 'AIQuoteDualSystem\logs\client.log'
    $taskLogText = Get-Content -LiteralPath $taskLog -Raw
    if ($taskLogText -notmatch 'V3 namespace loaded; entering Qt application') { throw 'Qt startup marker missing.' }
    if ($taskLogText -match 'client startup/runtime terminated with an error') { throw 'Startup error recorded.' }
    if ((Get-Item -LiteralPath $Entry).VersionInfo.ProductVersion -ne $Version) { throw 'Unexpected executable version.' }
    [ordered]@{ entry=$Entry; version=$Version; startup_passed=$true; qt_namespace_loaded=$true;
        test_process_id=$taskProcess.Id; production_quote_writes=0; log=$taskLog } | ConvertTo-Json
} finally {
    if ($taskProcess -and -not $taskProcess.HasExited) { Stop-Process -Id $taskProcess.Id }
    $env:LOCALAPPDATA = $taskPreviousProfile
    $env:QT_QPA_PLATFORM = $taskPreviousQt
    $env:TEMP = $taskPreviousTemp
    $env:TMP = $taskPreviousTmp
}
