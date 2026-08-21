param(
    [string]$NsisRoot = "G:\gongsi\banjinxitong\板件后续二次修改\.installer-tools\nsis-3.12\nsis-3.12",
    [string]$OutputRoot = "G:\gongsi\banjinxitong\板件后续二次修改\AIQuoteDualSystem_Installer"
)

$ErrorActionPreference = "Stop"
$packagingRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $packagingRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$currentClient = Join-Path $workspaceRoot "AIQuoteDualSystem"
$buildRoot = Join-Path $workspaceRoot ".installer-build-v2026.08.21.4"
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "work"
$stageRoot = Join-Path $buildRoot "stage"
$pythonExe = "D:\Program Files (x86)\Python\python.exe"
$pyInstaller = "G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\pyinstaller.exe"
$makeNsis = Join-Path $NsisRoot "makensis.exe"

foreach ($required in @($pythonExe, $pyInstaller, $makeNsis, (Join-Path $currentClient "client_config.json"))) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required build input is missing: $required"
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

& $pythonExe (Join-Path $packagingRoot "build_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed: $LASTEXITCODE" }

Push-Location $packagingRoot
try {
    & $pyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot (Join-Path $packagingRoot "AIQuoteDualSystem_installer.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
}
finally {
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

$entryPath = Join-Path $stageRoot "AIQuoteDualSystem_layout_v6.exe"
$iconPath = Join-Path $stageRoot "AIQuoteDualSystem.ico"
$entryHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $entryPath).Hash
$iconHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $iconPath).Hash
$files = Get-ChildItem -LiteralPath $stageRoot -Recurse -File
$manifest = [ordered]@{
    product = "AI Quote Dual System"
    version = "2026.08.21.4"
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
& $makeNsis "/DStageDir=$stageRoot" "/DOutputDir=$OutputRoot" $nsiCompile
if ($LASTEXITCODE -ne 0) { throw "NSIS compilation failed: $LASTEXITCODE" }

$installer = Join-Path $OutputRoot "AIQuoteDualSystem_Setup_v2026.08.21.4.exe"
$installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash
[ordered]@{
    installer = $installer
    bytes = (Get-Item -LiteralPath $installer).Length
    sha256 = $installerHash
    stage = $stageRoot
} | ConvertTo-Json
