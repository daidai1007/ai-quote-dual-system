$ErrorActionPreference = 'Stop'
$taskWorkspace = 'G:\gongsi\banjinxitong\板件后续二次修改'
$taskLive = Join-Path $taskWorkspace 'AIQuoteDualSystem'
$taskReview = Join-Path $taskWorkspace 'render-test-deploy\outputs\review-client-2026.10.09.09'
$taskStage = Join-Path $taskReview 'AIQuoteDualSystem'
$taskBuilt = Join-Path $taskReview 'dist\AIQuoteDualSystem_layout_v0'
$taskBackup = Join-Path $taskWorkspace '.client-backups\before-2026.10.09.09'
$taskEntry = Join-Path $taskLive 'AIQuoteDualSystem_layout_v0.exe'
$taskSourceEntry = Join-Path $taskStage 'AIQuoteDualSystem_layout_v0.exe'
$taskConfig = Join-Path $taskLive 'client_config.json'

foreach ($taskPath in @($taskLive, $taskBackup, $taskReview)) {
    $taskResolved = [IO.Path]::GetFullPath($taskPath)
    if (-not $taskResolved.StartsWith($taskWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Deployment path escaped workspace: $taskResolved"
    }
}
if ((Get-Item -LiteralPath $taskSourceEntry).VersionInfo.ProductVersion -ne '2026.10.09.09') {
    throw 'Unexpected build version.'
}
if (Get-Process | Where-Object { $_.Path -eq $taskEntry }) {
    throw 'The target client is still running; close it before deployment.'
}
if (Test-Path -LiteralPath $taskBackup) { throw 'Backup already exists; do not overwrite it.' }
$taskConfigHash = (Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash
$taskCoreHash = (Get-FileHash -LiteralPath (Join-Path $taskLive '_internal\v3_core\main.raw')).Hash
$taskNewHash = (Get-FileHash -LiteralPath $taskSourceEntry -Algorithm SHA256).Hash

# Back up the executable and runtime before replacing any live file.
New-Item -ItemType Directory -Path $taskBackup | Out-Null
Copy-Item -LiteralPath (Join-Path $taskLive '_internal') -Destination $taskBackup -Recurse
foreach ($taskName in @('AIQuoteDualSystem_layout_v0.exe', 'client_config.json', 'release-manifest.json')) {
    $taskExisting = Join-Path $taskLive $taskName
    if (Test-Path -LiteralPath $taskExisting) {
        Copy-Item -LiteralPath $taskExisting -Destination $taskBackup
    }
}
if ((Get-FileHash -LiteralPath (Join-Path $taskBackup 'AIQuoteDualSystem_layout_v0.exe')).Hash -ne
    (Get-FileHash -LiteralPath $taskEntry).Hash) { throw 'Executable backup verification failed.' }
if ((Get-FileHash -LiteralPath (Join-Path $taskBackup '_internal\v3_core\main.raw')).Hash -ne $taskCoreHash) {
    throw 'Core backup verification failed.'
}

$taskDependencies = Join-Path $taskBuilt '_internal'
$taskCopied = 0
Get-ChildItem -LiteralPath $taskDependencies -Recurse -File | ForEach-Object {
    $taskRelative = [IO.Path]::GetRelativePath($taskDependencies, $_.FullName)
    $taskDestination = Join-Path (Join-Path $taskLive '_internal') $taskRelative
    $taskUnchanged = (Test-Path -LiteralPath $taskDestination -PathType Leaf) -and (
        (Get-FileHash -LiteralPath $_.FullName).Hash -eq (Get-FileHash -LiteralPath $taskDestination).Hash
    )
    if (-not $taskUnchanged) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $taskDestination -Force
        $taskCopied += 1
    }
}
Copy-Item -LiteralPath $taskSourceEntry -Destination $taskEntry -Force
if ((Get-FileHash -LiteralPath $taskEntry -Algorithm SHA256).Hash -ne $taskNewHash) {
    throw 'Deployed executable differs from build.'
}
if ((Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash -ne $taskConfigHash) {
    throw 'Existing client configuration changed.'
}
if ((Get-FileHash -LiteralPath (Join-Path $taskLive '_internal\v3_core\main.raw')).Hash -ne $taskCoreHash) {
    throw 'Recovered quote core changed.'
}
$taskManifest = [ordered]@{
    version = '2026.10.09.09'
    current_entry = $taskEntry
    backup = $taskBackup
    sha256 = $taskNewHash
    config_preserved = $true
    quote_core_preserved = $true
    output_preserved = $true
    updated_runtime_files = $taskCopied
    bytes = (Get-Item -LiteralPath $taskEntry).Length
    deployed_at = (Get-Date).ToUniversalTime().ToString('o')
}
$taskManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskLive 'release-manifest.json') -Encoding utf8
$taskManifest | ConvertTo-Json
