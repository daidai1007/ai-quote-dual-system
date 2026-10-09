$ErrorActionPreference = 'Stop'
$taskWorkspace = 'G:\gongsi\banjinxitong\板件后续二次修改'
$taskLive = Join-Path $taskWorkspace 'AIQuoteDualSystem'
$taskReview = Join-Path $taskWorkspace 'render-test-deploy\outputs\review-client-2026.10.09.08'
$taskStage = Join-Path $taskReview 'AIQuoteDualSystem'
$taskBuilt = Join-Path $taskReview 'dist\AIQuoteDualSystem_layout_v0'
$taskBackup = Join-Path $taskWorkspace '.client-backups\before-2026.10.09.08'
$taskEntry = Join-Path $taskLive 'AIQuoteDualSystem_layout_v0.exe'
$taskSourceEntry = Join-Path $taskStage 'AIQuoteDualSystem_layout_v0.exe'
$taskConfig = Join-Path $taskLive 'client_config.json'
$taskIcon = Join-Path $taskWorkspace 'render-test-deploy\packaging\assets\AIQuoteDualSystem.ico'

foreach ($taskPath in @($taskLive, $taskBackup, $taskReview)) {
    $taskResolved = [IO.Path]::GetFullPath($taskPath)
    if (-not $taskResolved.StartsWith($taskWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Deployment path escaped workspace: $taskResolved"
    }
}
if (-not (Test-Path -LiteralPath $taskSourceEntry -PathType Leaf)) { throw 'Built client is missing.' }
if ((Get-Item -LiteralPath $taskSourceEntry).VersionInfo.ProductVersion -ne '2026.10.09.08') {
    throw 'Unexpected build version.'
}
$taskRunning = @(Get-Process | Where-Object {
    $_.Path -eq $taskEntry
})
if ($taskRunning.Count) { throw 'The target client is still running; close it before deployment.' }
$taskConfigHash = (Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash
$taskNewHash = (Get-FileHash -LiteralPath $taskSourceEntry -Algorithm SHA256).Hash

# Save every overwritten live runtime file before changing the installation.
if (-not (Test-Path -LiteralPath $taskBackup)) {
    New-Item -ItemType Directory -Path $taskBackup | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskLive '_internal') -Destination $taskBackup -Recurse
    foreach ($taskName in @('AIQuoteDualSystem_layout_v0.exe', 'client_config.json', 'release-manifest.json', 'AIQuoteDualSystem.ico', 'AIQuoteDualSystem_layout_v0.exe - 快捷方式.lnk')) {
        $taskExisting = Join-Path $taskLive $taskName
        if (Test-Path -LiteralPath $taskExisting) {
            Copy-Item -LiteralPath $taskExisting -Destination $taskBackup
        }
    }
} else {
    # An interrupted copy may be resumed only with the complete original backup.
    foreach ($taskName in @('AIQuoteDualSystem_layout_v0.exe', 'client_config.json', '_internal\v3_core\main.raw', '_internal\v3_core\original.pyz')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskBackup $taskName) -PathType Leaf)) {
            throw "Incomplete deployment backup: $taskName"
        }
    }
    if ((Get-FileHash -LiteralPath (Join-Path $taskBackup 'client_config.json')).Hash -ne $taskConfigHash) {
        throw 'Configuration changed since the backup was created.'
    }
}

$taskDependencies = Join-Path $taskBuilt '_internal'
Get-ChildItem -LiteralPath $taskDependencies -Recurse -File | ForEach-Object {
    $taskRelative = [IO.Path]::GetRelativePath($taskDependencies, $_.FullName)
    $taskDestination = Join-Path (Join-Path $taskLive '_internal') $taskRelative
    $taskUnchanged = (Test-Path -LiteralPath $taskDestination -PathType Leaf) -and (
        (Get-FileHash -LiteralPath $_.FullName).Hash -eq (Get-FileHash -LiteralPath $taskDestination).Hash
    )
    if (-not $taskUnchanged) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $taskDestination -Force
    }
}
Copy-Item -LiteralPath $taskSourceEntry -Destination $taskEntry -Force
Copy-Item -LiteralPath $taskIcon -Destination (Join-Path $taskLive 'AIQuoteDualSystem.ico') -Force

$taskShell = New-Object -ComObject WScript.Shell
$taskLink = $taskShell.CreateShortcut((Join-Path $taskLive 'AIQuoteDualSystem_layout_v0.exe - 快捷方式.lnk'))
$taskLink.TargetPath = $taskEntry
$taskLink.WorkingDirectory = $taskLive
$taskLink.IconLocation = Join-Path $taskLive 'AIQuoteDualSystem.ico'
$taskLink.Save()

foreach ($taskDeployed in @($taskEntry)) {
    if ((Get-FileHash -LiteralPath $taskDeployed -Algorithm SHA256).Hash -ne $taskNewHash) {
        throw "Deployed executable differs from build: $taskDeployed"
    }
}
if ((Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash -ne $taskConfigHash) {
    throw 'Existing client configuration changed.'
}
[ordered]@{
    version = '2026.10.09.08'
    current_entry = $taskEntry
    backup = $taskBackup
    sha256 = $taskNewHash
    config_preserved = $true
    bytes = (Get-Item -LiteralPath $taskEntry).Length
    deployed_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json
