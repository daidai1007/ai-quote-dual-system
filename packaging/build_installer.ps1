param(
    [string]$NsisRoot = "G:\gongsi\banjinxitong\板件后续二次修改\.installer-tools\nsis-3.12\nsis-3.12",
    [string]$OutputRoot = "G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem_Installer",
    [string]$Version = "2026.08.29",
    [string]$PythonExe = "G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$packagingRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $packagingRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$currentClient = Join-Path $workspaceRoot "AIQuoteDualSystem"
$buildRoot = Join-Path $workspaceRoot ".installer-build-v$Version"
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "work"
$stageRoot = Join-Path $buildRoot "stage"
$pythonExe = $PythonExe
$pyInstaller = Join-Path (Split-Path -Parent $pythonExe) "pyinstaller.exe"
$makeNsis = Join-Path $NsisRoot "makensis.exe"

if ($Version -notmatch '^\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?$') {
    throw "Version must use YYYY.MM.DD or YYYY.MM.DD.build format: $Version"
}
$versionParts = @($Version.Split('.') | ForEach-Object { [int]$_ })
while ($versionParts.Count -lt 4) { $versionParts += 0 }
$numericVersion = ($versionParts[0..3] -join '.')

foreach ($required in @($pythonExe, $pyInstaller, $makeNsis, (Join-Path $currentClient "client_config.json"))) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required build input is missing: $required"
    }
}

& $pythonExe -c "import struct,sys; assert sys.version_info[:2] == (3, 12), sys.version; assert struct.calcsize('P') * 8 == 64, 'Python must be 64-bit'"
if ($LASTEXITCODE -ne 0) {
    throw "Installer builds require Python 3.12 x64: $pythonExe"
}

$currentCore = Join-Path $currentClient "_internal\v3_core"
foreach ($requiredCoreFile in @("main.raw", "original.pyz")) {
    $requiredCorePath = Join-Path $currentCore $requiredCoreFile
    if (-not (Test-Path -LiteralPath $requiredCorePath -PathType Leaf)) {
        throw "Validated V3 runtime core is incomplete: $requiredCorePath"
    }
}

$resolvedBuild = [System.IO.Path]::GetFullPath($buildRoot)
$resolvedWorkspace = [System.IO.Path]::GetFullPath($workspaceRoot)
if (-not $resolvedBuild.StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe build path: $resolvedBuild"
}
if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $buildRoot, $distRoot, $workRoot, $stageRoot, $OutputRoot | Out-Null

$artworkFiles = @(
    (Join-Path $packagingRoot "assets\AIQuoteDualSystem.ico"),
    (Join-Path $packagingRoot "assets\installer_sidebar.bmp"),
    (Join-Path $packagingRoot "assets\installer_header.bmp")
)
& $pythonExe -c "import PIL" 2>$null
if ($LASTEXITCODE -eq 0) {
    & $pythonExe (Join-Path $packagingRoot "build_icon.py")
    if ($LASTEXITCODE -ne 0) { throw "Icon generation failed: $LASTEXITCODE" }
}
else {
    foreach ($artworkFile in $artworkFiles) {
        if (-not (Test-Path -LiteralPath $artworkFile -PathType Leaf)) {
            throw "Pillow is unavailable and packaged artwork is missing: $artworkFile"
        }
    }
    Write-Warning "Pillow is not installed; reusing the validated packaged artwork."
}

Push-Location $packagingRoot
try {
    $env:AI_QUOTE_BUILD_VERSION = $Version
    $env:AI_QUOTE_VERSION_FILE = Join-Path $buildRoot "version_info.generated.txt"
    & $pyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot (Join-Path $packagingRoot "AIQuoteDualSystem_installer.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
}
finally {
    Remove-Item Env:AI_QUOTE_BUILD_VERSION -ErrorAction SilentlyContinue
    Remove-Item Env:AI_QUOTE_VERSION_FILE -ErrorAction SilentlyContinue
    Pop-Location
}

$builtClient = Join-Path $distRoot "AIQuoteDualSystem_layout_v6"
Copy-Item -LiteralPath (Join-Path $builtClient "AIQuoteDualSystem_layout_v6.exe") -Destination (Join-Path $stageRoot "AIQuoteDualSystem_layout_v6.exe") -Force
Copy-Item -LiteralPath (Join-Path $currentClient "_internal") -Destination (Join-Path $stageRoot "_internal") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $currentClient "runtime") -Destination (Join-Path $stageRoot "runtime") -Recurse -Force
foreach ($name in @("client_config.json", "PROJECT-LICENSE.txt", "README.txt", "THIRD_PARTY_NOTICES.txt")) {
    Copy-Item -LiteralPath (Join-Path $currentClient $name) -Destination (Join-Path $stageRoot $name) -Force
}
Copy-Item -LiteralPath (Join-Path $packagingRoot "assets\AIQuoteDualSystem.ico") -Destination (Join-Path $stageRoot "AIQuoteDualSystem.ico") -Force
Copy-Item -LiteralPath (Join-Path $packagingRoot "assets\installer_sidebar.bmp") -Destination (Join-Path $stageRoot "installer_sidebar.bmp") -Force
Copy-Item -LiteralPath (Join-Path $packagingRoot "assets\installer_header.bmp") -Destination (Join-Path $stageRoot "installer_header.bmp") -Force
New-Item -ItemType Directory -Force -Path (Join-Path $stageRoot "output") | Out-Null

$stagedCore = Join-Path $stageRoot "_internal\v3_core"
foreach ($requiredCoreFile in @("main.raw", "original.pyz")) {
    $requiredCorePath = Join-Path $stagedCore $requiredCoreFile
    if (-not (Test-Path -LiteralPath $requiredCorePath -PathType Leaf)) {
        throw "Installer stage omitted the required V3 runtime core: $requiredCorePath"
    }
}
$sourceCoreFiles = @(Get-ChildItem -LiteralPath $currentCore -Recurse -File)
$stagedCoreFiles = @(Get-ChildItem -LiteralPath $stagedCore -Recurse -File)
if ($sourceCoreFiles.Count -ne $stagedCoreFiles.Count) {
    throw "V3 runtime core file count changed during staging: source=$($sourceCoreFiles.Count), stage=$($stagedCoreFiles.Count)"
}

$entryPath = Join-Path $stageRoot "AIQuoteDualSystem_layout_v6.exe"
$iconPath = Join-Path $stageRoot "AIQuoteDualSystem.ico"
$entryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $entryPath).Hash
$iconHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $iconPath).Hash
$files = Get-ChildItem -LiteralPath $stageRoot -Recurse -File
$manifest = [ordered]@{
    product = "AI Quote Dual System"
    version = $Version
    entry = "AIQuoteDualSystem_layout_v6.exe"
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    architecture = "win-x64"
    installer = "NSIS 3.12"
    signature_status = "NotSigned"
    package_file_count = $files.Count
    package_bytes = [long](($files | Measure-Object Length -Sum).Sum)
    note = "Branded installer build of the validated unified-door V3 client; application logic and cloud API contract are unchanged."
    critical_files = @(
        [ordered]@{ path = "AIQuoteDualSystem_layout_v6.exe"; bytes = (Get-Item -LiteralPath $entryPath).Length; sha256 = $entryHash },
        [ordered]@{ path = "AIQuoteDualSystem.ico"; bytes = (Get-Item -LiteralPath $iconPath).Length; sha256 = $iconHash }
    )
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stageRoot "release-manifest.json") -Encoding utf8

$nsiSource = Join-Path $packagingRoot "AIQuoteDualSystem.nsi"
$nsiCompile = Join-Path $buildRoot "AIQuoteDualSystem.compile.nsi"
$nsiText = [System.IO.File]::ReadAllText($nsiSource)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($nsiCompile, $nsiText, $utf8Bom)
& $makeNsis "/DStageDir=$stageRoot" "/DOutputDir=$OutputRoot" "/DAppVersion=$Version" "/DAppVersionNumeric=$numericVersion" $nsiCompile
if ($LASTEXITCODE -ne 0) { throw "NSIS compilation failed: $LASTEXITCODE" }

$installer = Join-Path $OutputRoot "AIQuoteDualSystem_Setup_v$Version.exe"
$installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash
[ordered]@{
    installer = $installer
    bytes = (Get-Item -LiteralPath $installer).Length
    sha256 = $installerHash
    stage = $stageRoot
} | ConvertTo-Json
