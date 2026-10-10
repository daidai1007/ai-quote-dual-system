param([Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d{4}\.\d{2}\.\d{2}\.\d+$') { throw 'Invalid version.' }
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskWorkspace = Split-Path -Parent $taskRepo
$taskLive = Join-Path $taskWorkspace 'AIQuoteDualSystem'
$taskReview = Join-Path $taskRepo "outputs\review-client-$Version"
$taskBuilt = Join-Path $taskReview 'dist\AIQuoteDualSystem_layout_v0'
$taskBackup = Join-Path $taskWorkspace ".client-backups\before-$Version"
$taskEntry = Join-Path $taskLive 'AIQuoteDualSystem_layout_v0.exe'
$taskSourceEntry = Join-Path $taskReview 'AIQuoteDualSystem\AIQuoteDualSystem_layout_v0.exe'
$taskConfig = Join-Path $taskLive 'client_config.json'
foreach ($taskPath in @($taskLive, $taskReview, $taskBuilt, $taskBackup)) {
    if (-not ([IO.Path]::GetFullPath($taskPath)).StartsWith($taskWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Deployment path escaped workspace: $taskPath"
    }
}
if ((Get-Item -LiteralPath $taskSourceEntry).VersionInfo.ProductVersion -ne $Version) { throw 'Unexpected build version.' }
if (Get-Process | Where-Object { $_.Path -eq $taskEntry }) { throw 'Close the target client before deployment.' }
$taskExclusive = [IO.File]::Open($taskEntry, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
$taskExclusive.Dispose()
$taskConfigHash = (Get-FileHash -LiteralPath $taskConfig).Hash
$taskCoreHash = (Get-FileHash -LiteralPath (Join-Path $taskLive '_internal\v3_core\main.raw')).Hash
$taskNewHash = (Get-FileHash -LiteralPath $taskSourceEntry).Hash
$taskOutputs = @(Get-ChildItem -LiteralPath (Join-Path $taskLive 'output') -Recurse -File | ForEach-Object {
    $taskHash = $null
    try { $taskHash = (Get-FileHash -LiteralPath $_.FullName -ErrorAction Stop).Hash }
    catch [IO.IOException] { }
    [pscustomobject]@{ Path=$_.FullName; Hash=$taskHash; Length=$_.Length; Written=$_.LastWriteTimeUtc }
})
if (Test-Path -LiteralPath $taskBackup) { throw "Backup already exists; inspect before reusing: $taskBackup" }
New-Item -ItemType Directory -Path $taskBackup | Out-Null
Copy-Item -LiteralPath (Join-Path $taskLive '_internal') -Destination $taskBackup -Recurse
foreach ($taskName in @('AIQuoteDualSystem_layout_v0.exe','client_config.json','release-manifest.json')) {
    $taskExisting = Join-Path $taskLive $taskName
    if (Test-Path -LiteralPath $taskExisting) { Copy-Item -LiteralPath $taskExisting -Destination $taskBackup }
}
foreach ($taskName in @('AIQuoteDualSystem_layout_v0.exe','client_config.json','_internal\v3_core\main.raw')) {
    if ((Get-FileHash -LiteralPath (Join-Path $taskBackup $taskName)).Hash -ne
        (Get-FileHash -LiteralPath (Join-Path $taskLive $taskName)).Hash) { throw "Backup verification failed: $taskName" }
}
$taskCopied = 0
$taskDependencies = Join-Path $taskBuilt '_internal'
Get-ChildItem -LiteralPath $taskDependencies -Recurse -File | ForEach-Object {
    $taskRelative = [IO.Path]::GetRelativePath($taskDependencies, $_.FullName)
    $taskDestination = Join-Path (Join-Path $taskLive '_internal') $taskRelative
    $taskUnchanged = (Test-Path -LiteralPath $taskDestination -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $_.FullName).Hash -eq (Get-FileHash -LiteralPath $taskDestination).Hash)
    if (-not $taskUnchanged) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $taskDestination -Force
        if ((Get-FileHash -LiteralPath $_.FullName).Hash -ne (Get-FileHash -LiteralPath $taskDestination).Hash) {
            throw "Runtime copy verification failed: $taskRelative"
        }
        $taskCopied += 1
    }
}
Copy-Item -LiteralPath $taskSourceEntry -Destination $taskEntry -Force
if ((Get-FileHash -LiteralPath $taskEntry).Hash -ne $taskNewHash) { throw 'Executable differs from build.' }
if ((Get-FileHash -LiteralPath $taskConfig).Hash -ne $taskConfigHash) { throw 'Client configuration changed.' }
if ((Get-FileHash -LiteralPath (Join-Path $taskLive '_internal\v3_core\main.raw')).Hash -ne $taskCoreHash) { throw 'Quote core changed.' }
foreach ($taskOutput in $taskOutputs) {
    $taskPreserved = Get-Item -LiteralPath $taskOutput.Path
    if ($taskPreserved.Length -ne $taskOutput.Length -or $taskPreserved.LastWriteTimeUtc -ne $taskOutput.Written) { throw 'Existing output changed.' }
    if ($taskOutput.Hash -and (Get-FileHash -LiteralPath $taskOutput.Path).Hash -ne $taskOutput.Hash) { throw 'Output content changed.' }
}
$taskManifest = [ordered]@{
    version=$Version; current_entry=$taskEntry; backup=$taskBackup; sha256=$taskNewHash;
    config_preserved=$true; quote_core_preserved=$true; output_preserved=$true;
    updated_runtime_files=$taskCopied; bytes=(Get-Item -LiteralPath $taskEntry).Length;
    deployed_at=(Get-Date).ToUniversalTime().ToString('o')
}
$taskManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskLive 'release-manifest.json') -Encoding utf8
$taskManifest | ConvertTo-Json
