param([switch]$AllowPendingDeployment)
$ErrorActionPreference = 'Stop'
$taskWorkspace = 'G:\gongsi\banjinxitong\板件后续二次修改'
$taskSource = Join-Path $taskWorkspace 'render-test-deploy\outputs\review-client-2026.10.09.11\AIQuoteDualSystem'
$taskLive = Join-Path $taskWorkspace 'AIQuoteDualSystem'
$taskZip = Join-Path $taskWorkspace 'AIQuoteDualSystem_Portable_v2026.10.09.11.zip'
foreach ($taskPath in @($taskSource, $taskZip)) {
    if (-not [IO.Path]::GetFullPath($taskPath).StartsWith($taskWorkspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Archive path escaped the workspace.'
    }
}
if (Test-Path -LiteralPath $taskZip) { throw 'Archive already exists; do not overwrite it.' }
$taskEntry = Join-Path $taskSource 'AIQuoteDualSystem_layout_v0.exe'
if ((Get-Item -LiteralPath $taskEntry).VersionInfo.ProductVersion -ne '2026.10.09.11') {
    throw 'Portable client has the wrong version.'
}
$taskExeHash = (Get-FileHash -LiteralPath $taskEntry -Algorithm SHA256).Hash
$taskMatchesCurrent = $taskExeHash -eq (Get-FileHash -LiteralPath (Join-Path $taskLive 'AIQuoteDualSystem_layout_v0.exe')).Hash
$taskBuildManifest = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $taskSource) 'manifest.json') -Raw | ConvertFrom-Json
if ($taskBuildManifest.version -ne '2026.10.09.11' -or $taskBuildManifest.sha256 -ne $taskExeHash) {
    throw 'Portable executable differs from the verified build manifest.'
}
if (-not $taskMatchesCurrent -and -not $AllowPendingDeployment) {
    throw 'Portable executable differs from the current client.'
}
if ((Get-FileHash -LiteralPath (Join-Path $taskSource 'client_config.json')).Hash -ne
    (Get-FileHash -LiteralPath (Join-Path $taskLive 'client_config.json')).Hash) {
    throw 'Portable API configuration differs from the current client.'
}
$taskFiles = @(Get-ChildItem -LiteralPath $taskSource -Recurse -File)
if ($taskFiles | Where-Object { $_.FullName -match '\\output\\|\\logs\\|\\Uninstall\.exe$|\.backup' }) {
    throw 'Portable stage contains old output, logs, uninstaller or backups.'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($taskSource, $taskZip, [IO.Compression.CompressionLevel]::Optimal, $true)
$taskArchive = [IO.Compression.ZipFile]::OpenRead($taskZip)
$taskSha = [Security.Cryptography.SHA256]::Create()
try {
    $taskNames = @{}
    foreach ($taskMember in $taskArchive.Entries) {
        if ($taskNames.ContainsKey($taskMember.FullName)) { throw 'Duplicate ZIP member.' }
        $taskNames[$taskMember.FullName] = $taskMember
    }
    foreach ($taskFile in $taskFiles) {
        $taskRelative = [IO.Path]::GetRelativePath($taskSource, $taskFile.FullName).Replace('\', '/')
        $taskName = 'AIQuoteDualSystem/' + $taskRelative
        if (-not $taskNames.ContainsKey($taskName)) { throw "Missing ZIP member: $taskName" }
        $taskMember = $taskNames[$taskName]
        if ($taskMember.Length -ne $taskFile.Length) { throw "Wrong ZIP member size: $taskName" }
        $taskStream = $taskMember.Open()
        try { $taskMemberHash = [Convert]::ToHexString($taskSha.ComputeHash($taskStream)) }
        finally { $taskStream.Dispose() }
        if ($taskMemberHash -ne (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash) {
            throw "Corrupt ZIP member: $taskName"
        }
    }
    if (@($taskArchive.Entries | Where-Object { $_.Name }).Count -ne $taskFiles.Count) {
        throw 'Unexpected extra files in ZIP.'
    }
} finally {
    $taskSha.Dispose()
    $taskArchive.Dispose()
}
[ordered]@{
    archive = $taskZip
    version = '2026.10.09.11'
    bytes = (Get-Item -LiteralPath $taskZip).Length
    file_count = $taskFiles.Count
    sha256 = (Get-FileHash -LiteralPath $taskZip -Algorithm SHA256).Hash
    executable_matches_current_client = $taskMatchesCurrent
    executable_matches_verified_build = $true
    every_archive_member_verified = $true
    existing_api_configuration_preserved = $true
    old_quote_outputs_included = $false
} | ConvertTo-Json
