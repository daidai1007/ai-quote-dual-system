param([string]$ClientDirectory = '')
$ErrorActionPreference = 'Stop'
$Version = '__VERSION__'
$ExpectedPackageHash = '__PACKAGE_SHA256__'
$ExpectedPackageSize = __PACKAGE_SIZE__
$ExpectedManifestHash = '__MANIFEST_SHA256__'
$ExpectedEntryHash = '__ENTRY_SHA256__'
$ExpectedCasefoldHash = '__CASEFOLD_SHA256__'
$ExpectedPublicKey = '__PUBLIC_KEY__'
$Origin = 'http://192.168.35.212:8898'
$Entry = 'AIQuoteDualSystem_layout_v0.exe'

function Hash-File([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Write-Json([string]$Path, $Value) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30), $encoding)
}
function Assert-NoLinks([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Links/junctions are not supported.' }
        if ($item -is [IO.DirectoryInfo]) { $item = $item.Parent } else { $item = $item.Directory }
    }
}
function Assert-Closed([string]$Path) {
    $handle = $null
    try { $handle = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None) }
    catch { throw '请先保存进度并关闭该目录的客户端，再运行兼容升级工具。' }
    finally { if ($null -ne $handle) { $handle.Dispose() } }
}
function Fold-Path([string]$Text, $Mapping) {
    $builder = New-Object Text.StringBuilder
    for ($index = 0; $index -lt $Text.Length; $index++) {
        $codepoint = [char]::ConvertToUtf32($Text, $index)
        $piece = [char]::ConvertFromUtf32($codepoint)
        if ($codepoint -gt 65535) { $index++ }
        $mapped = $Mapping.PSObject.Properties[$codepoint.ToString()]
        if ($null -ne $mapped) { [void]$builder.Append([string]$mapped.Value) } else { [void]$builder.Append($piece) }
    }
    return $builder.ToString()
}

if (-not $ClientDirectory) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object Windows.Forms.FolderBrowserDialog
    $picker.Description = '选择旧版 AI 双报价系统所在文件夹（先保存进度并退出客户端）'
    $picker.ShowNewFolderButton = $false
    if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return }
    $ClientDirectory = $picker.SelectedPath
}
$target = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ClientDirectory).ProviderPath).TrimEnd('\')
if ($target.StartsWith('\\') -or $target -eq [IO.Path]::GetPathRoot($target).TrimEnd('\')) { throw 'Choose a local existing client folder.' }
Assert-NoLinks $target
$installedEntry = Join-Path $target $Entry
if (-not (Test-Path -LiteralPath $installedEntry -PathType Leaf)) { throw '该文件夹中没有客户端主程序。' }
$installedVersionText = (Get-Item -LiteralPath $installedEntry).VersionInfo.FileVersion
$installedVersion = [Version]$installedVersionText
if ($installedVersion -ge [Version]$Version) { Write-Output "当前已是 $installedVersion，无需运行本次兼容升级。"; return }
if ($installedVersion -lt [Version]'2026.10.20.05') { throw '该旧版本不在本工具验证范围内，请联系发布人员。' }
Assert-Closed $installedEntry
$updateFile = Join-Path $target 'update_config.json'
$config = Get-Content -LiteralPath $updateFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.enabled -ne $true -or $config.channel -ne 'local' -or $config.public_key -cne $ExpectedPublicKey -or
    $config.lan_http_origin -cne $Origin -or $config.manifest_url -cne ($Origin + '/stable/manifest.json')) {
    throw '更新源或验证公钥与可信发布配置不一致；未修改客户端。'
}
$manifestPath = Join-Path $PSScriptRoot 'manifest.json'
$foldPath = Join-Path $PSScriptRoot 'python-casefold.json'
if ((Hash-File $manifestPath) -ne $ExpectedManifestHash -or (Hash-File $foldPath) -ne $ExpectedCasefoldHash) { throw '兼容工具文件哈希不匹配；未修改客户端。' }
$manifestRaw = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8)
$envelope = $manifestRaw | ConvertFrom-Json
$release = $envelope.release
$packageName = "AIQuoteDualSystem-$Version.zip"
if ($release.version -cne $Version -or $release.channel -cne 'local' -or $release.product -cne 'AIQuoteDualSystem' -or
    $release.sha256 -cne $ExpectedPackageHash -or $release.size -ne $ExpectedPackageSize -or
    $release.url -cne ($Origin + '/' + $Version + '/' + $packageName)) { throw '发布清单与可信固定值不一致。' }
$identity = [guid]::NewGuid().ToString('N')
$work = Join-Path $env:LOCALAPPDATA ('AIQuoteDualSystem\compat-upgrades\' + $identity)
Assert-NoLinks $env:LOCALAPPDATA
New-Item -ItemType Directory -Path $work -ErrorAction Stop | Out-Null
Assert-NoLinks $work
$package = Join-Path $work $packageName
$adjacent = Join-Path $PSScriptRoot $packageName
if (Test-Path -LiteralPath $adjacent -PathType Leaf) {
    Assert-NoLinks $adjacent
    Copy-Item -LiteralPath $adjacent -Destination $package
} else {
    Write-Output '正在从已绑定的内网源下载程序包；不切换更新清单。'
    $request = [Net.HttpWebRequest]::Create([string]$release.url)
    $request.Proxy = $null; $request.AllowAutoRedirect = $false; $request.Timeout = 30000; $request.ReadWriteTimeout = 30000
    $response = $null; $inputStream = $null; $outputStream = $null
    try {
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200 -or $response.ContentLength -ne $ExpectedPackageSize) { throw '程序包响应不完整。' }
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Open($package,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $buffer = New-Object byte[] 262144
        [long]$received = 0
        while (($count = $inputStream.Read($buffer,0,$buffer.Length)) -gt 0) {
            $received += $count
            if ($received -gt $ExpectedPackageSize) { throw '程序包超出签名清单大小。' }
            $outputStream.Write($buffer,0,$count)
        }
    } finally {
        if ($null -ne $outputStream) { $outputStream.Dispose() }
        if ($null -ne $inputStream) { $inputStream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
    }
}
if ((Get-Item -LiteralPath $package).Length -ne $ExpectedPackageSize -or (Hash-File $package) -ne $ExpectedPackageHash) { throw '程序包哈希/大小不匹配；未修改客户端。' }
$runner = Join-Path $work 'runner'
New-Item -ItemType Directory -Path $runner | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($package)
$names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$files = New-Object 'System.Collections.Generic.List[string]'
try {
    [long]$expanded = ($archive.Entries | Measure-Object -Property Length -Sum).Sum
    [long]$existingBytes = (Get-ChildItem -LiteralPath $target -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    $workDrive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($work))
    $targetDrive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($target))
    [long]$workBudget = $expanded * 3 + $ExpectedPackageSize * 2 + 536870912
    [long]$targetBudget = $existingBytes + $expanded + 536870912
    if ($workDrive.Name -eq $targetDrive.Name) {
        if ($workDrive.AvailableFreeSpace -lt ($workBudget + $targetBudget)) { throw '磁盘空间不足，未修改客户端。' }
    } elseif ($workDrive.AvailableFreeSpace -lt $workBudget -or $targetDrive.AvailableFreeSpace -lt $targetBudget) {
        throw '磁盘空间不足，未修改客户端。'
    }
    foreach ($member in $archive.Entries) {
        $name = $member.FullName
        if ($name.EndsWith('/')) { throw 'Unexpected directory entry in the verified program package.' }
        if ($name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/') -or $name -match '(^|/)\.\.?(/|$)' -or -not $names.Add($name)) { throw 'Unsafe/duplicate package member.' }
        $destination = [IO.Path]::GetFullPath((Join-Path $runner $name))
        if (-not $destination.StartsWith($runner + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Package member escapes the runner folder.' }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($member,$destination,$false)
        $files.Add($name)
    }
} finally { $archive.Dispose() }
$runnerEntry = Join-Path $runner $Entry
if ((Hash-File $runnerEntry) -ne $ExpectedEntryHash) { throw '新版更新器主程序与可信构建不一致；未修改客户端。' }
if ((Get-Item -LiteralPath $runnerEntry).VersionInfo.FileVersion -cne $Version) { throw '新版更新器版本不匹配。' }
Assert-Closed $installedEntry
$oldHash = Hash-File $installedEntry
$all = @(Get-ChildItem -LiteralPath $target -Recurse -Force)
foreach ($item in $all) { if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Client contains links/junctions; nothing replaced.' } }
$oldFiles = @{}; $oldDirectories = @()
foreach ($item in $all) {
    $relative = $item.FullName.Substring($target.Length + 1)
    if ($item.PSIsContainer) { $oldDirectories += $relative } else { $oldFiles[$relative] = Hash-File $item.FullName }
}
$backupRoot = Join-Path (Split-Path -Parent $target) '.client-backups'
$backup = [IO.Path]::GetFullPath((Join-Path $backupRoot ("before-$Version-compat-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $identity.Substring(0,8))))
if (-not $backup.StartsWith([IO.Path]::GetFullPath($backupRoot).TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup path escapes its root.' }
if (Test-Path -LiteralPath $backupRoot) { Assert-NoLinks $backupRoot }
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
foreach ($name in $oldDirectories) { [IO.Directory]::CreateDirectory((Join-Path $backup $name)) | Out-Null }
foreach ($name in $oldFiles.Keys) {
    $destination = Join-Path $backup $name
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
    Copy-Item -LiteralPath (Join-Path $target $name) -Destination $destination
    if ((Hash-File $destination) -ne $oldFiles[$name]) { throw 'Full backup verification failed; nothing replaced.' }
}
Write-Json (Join-Path $backup 'backup-file-hashes.json') $oldFiles
Assert-Closed $installedEntry
$nowFiles = @(Get-ChildItem -LiteralPath $target -Recurse -File -Force)
if ($nowFiles.Count -ne $oldFiles.Count) { throw 'Client changed during backup; nothing replaced.' }
foreach ($name in $oldFiles.Keys) { if ((Hash-File (Join-Path $target $name)) -ne $oldFiles[$name]) { throw 'Client changed during backup; nothing replaced.' } }
$mapping = Get-Content -LiteralPath $foldPath -Raw -Encoding UTF8 | ConvertFrom-Json
$folded = Fold-Path $target $mapping
$sha = [Security.Cryptography.SHA256]::Create()
try { $cacheId = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($folded)))).Replace('-','').ToLowerInvariant().Substring(0,20) }
finally { $sha.Dispose() }
$cacheParent = Join-Path $env:LOCALAPPDATA ('AIQuoteDualSystem\updates\' + $cacheId)
if (Test-Path -LiteralPath $cacheParent) { Assert-NoLinks $cacheParent }
$transaction = Join-Path $cacheParent $identity
New-Item -ItemType Directory -Path $transaction -ErrorAction Stop | Out-Null
Assert-NoLinks $transaction
Copy-Item -LiteralPath $package -Destination (Join-Path $transaction 'package.zip')
$job = [ordered]@{schema=1;install_root=$target;current_version=$installedVersionText;old_exe_sha256=$oldHash;config=$config;
    envelope=$null;files=@($files.ToArray());parent_pid=$PID;token=[guid]::NewGuid().ToString('N');status='prepared';workspace=''}
$jobPath = Join-Path $transaction 'job.json'
# Preserve signed JSON strings exactly, including timestamps in PowerShell 7.
$jobJson = $job | ConvertTo-Json -Depth 30
$jobJson = [regex]::Replace($jobJson, '"envelope"\s*:\s*null', { param($match) '"envelope": ' + $manifestRaw })
[IO.File]::WriteAllText($jobPath, $jobJson, (New-Object Text.UTF8Encoding($false)))
$receipt = [ordered]@{version=$Version;target=$target;backup=$backup;full_backup_files_verified=$oldFiles.Count;
    transaction=$jobPath;runner=$runnerEntry;runner_sha256=$ExpectedEntryHash;program_package_sha256=$ExpectedPackageHash;
    installed_client_modified_by_launcher=$false;server_written=$false;api_deployed=$false;database_written=$false}
Write-Json (Join-Path $work 'compat-started.json') $receipt
$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = $runnerEntry; $start.Arguments = '--client-updater "' + $jobPath + '"'
$start.WorkingDirectory = $runner; $start.UseShellExecute = $false; $start.CreateNoWindow = $true
[Diagnostics.Process]::Start($start) | Out-Null
Write-Output ('完整备份已核对：' + $backup)
Write-Output '新版更新器已启动，正在等待本工具自然退出。请在随后出现的姓名窗口中输入本人姓名。'
Write-Output '等待姓名期间不计入主窗口30秒时限；启动失败时由更新器恢复旧版。服务器清单不变。'
