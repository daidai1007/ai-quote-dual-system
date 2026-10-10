param([string]$Entry = 'G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy\outputs\review-client-2026.10.09.11\AIQuoteDualSystem\AIQuoteDualSystem_layout_v0.exe')
$ErrorActionPreference = 'Stop'
$taskProfile = 'G:\gongsi\banjinxitong\板件后续二次修改\render-test-deploy\outputs\startup-smoke-2026.10.09.11'
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
    [ordered]@{ entry = $Entry; version = (Get-Item -LiteralPath $Entry).VersionInfo.ProductVersion;
        startup_passed = $true; qt_namespace_loaded = $true; test_process_id = $taskProcess.Id;
        production_quote_writes = 0; log = $taskLog } | ConvertTo-Json
} finally {
    # Only the hidden smoke-test process started above is stopped.
    if ($taskProcess -and -not $taskProcess.HasExited) { Stop-Process -Id $taskProcess.Id }
    $env:LOCALAPPDATA = $taskPreviousProfile
    $env:QT_QPA_PLATFORM = $taskPreviousQt
    $env:TEMP = $taskPreviousTemp
    $env:TMP = $taskPreviousTmp
}
