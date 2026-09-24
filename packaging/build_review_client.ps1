param(
    [string]$Version = '2026.09.15.1',
    [string]$PythonExe = 'G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe',
    [string]$PreviewDependencies = '',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$currentClient = Join-Path (Split-Path -Parent $repoRoot) 'AIQuoteDualSystem'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot "outputs\review-client-$Version" }
$reviewRoot = [IO.Path]::GetFullPath($OutputDirectory)
$repoPath = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
if (-not $reviewRoot.StartsWith($repoPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Review builds must stay inside the repository.'
}
if (Test-Path -LiteralPath $reviewRoot) { throw "Review output already exists: $reviewRoot" }
$entry = Join-Path $currentClient 'AIQuoteDualSystem_layout_v0.exe'
$config = Join-Path $currentClient 'client_config.json'
$protectedBefore = @(Get-FileHash -LiteralPath $entry,$config -Algorithm SHA256)
New-Item -ItemType Directory -Path $reviewRoot | Out-Null
$env:AI_QUOTE_BUILD_VERSION = $Version
$env:AI_QUOTE_VERSION_FILE = Join-Path $reviewRoot 'version_info.txt'
$savedPythonPath = $env:PYTHONPATH
try {
    if ($PreviewDependencies) {
        $env:AI_QUOTE_PREVIEW_DEPS = (Resolve-Path -LiteralPath $PreviewDependencies).Path
        $env:PYTHONPATH = $env:AI_QUOTE_PREVIEW_DEPS
    }
    & $PythonExe -c "from ezdxf.addons.drawing import svg; import PIL; import PySide6.QtSvg"
    if ($LASTEXITCODE -ne 0) { throw 'Install desktop_client/requirements.txt before building.' }
    # PyInstaller uses stderr for informational logging; Windows PowerShell 5
    # must not interpret those INFO lines as terminating PowerShell errors.
    $ErrorActionPreference = 'Continue'
    & $PythonExe -m PyInstaller --noconfirm --distpath (Join-Path $reviewRoot 'dist') --workpath (Join-Path $reviewRoot 'work') (Join-Path $PSScriptRoot 'AIQuoteDualSystem_installer.spec') *> (Join-Path $reviewRoot 'build.log')
    $buildExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($buildExit -ne 0) { throw "Build failed; see $reviewRoot\build.log" }
    $built = Join-Path $reviewRoot 'dist\AIQuoteDualSystem_layout_v0'
    $portable = Join-Path $reviewRoot 'AIQuoteDualSystem'
    New-Item -ItemType Directory -Path $portable | Out-Null
    # The verified recovered core and tools are unchanged. New Python/Qt/CAD
    # dependencies overlay only this new portable directory, never the live app.
    Copy-Item -LiteralPath (Join-Path $currentClient '_internal') -Destination $portable -Recurse
    Copy-Item -LiteralPath (Join-Path $currentClient 'runtime') -Destination $portable -Recurse
    Get-ChildItem -LiteralPath (Join-Path $built '_internal') | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $portable '_internal') -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $built 'AIQuoteDualSystem_layout_v0.exe') -Destination $portable
    foreach ($name in @('client_config.json','PROJECT-LICENSE.txt','THIRD_PARTY_NOTICES.txt')) {
        Copy-Item -LiteralPath (Join-Path $currentClient $name) -Destination $portable
    }
    New-Item -ItemType Directory -Path (Join-Path $portable 'output') | Out-Null
    $builtEntry = Join-Path $portable 'AIQuoteDualSystem_layout_v0.exe'
    $protectedAfter = @(Get-FileHash -LiteralPath $entry,$config -Algorithm SHA256)
    if (Compare-Object $protectedBefore.Hash $protectedAfter.Hash) { throw 'Protected files unexpectedly changed.' }
    $coreBefore = Get-FileHash -LiteralPath (Join-Path $currentClient '_internal\v3_core\main.raw')
    $coreAfter = Get-FileHash -LiteralPath (Join-Path $portable '_internal\v3_core\main.raw')
    if ($coreBefore.Hash -ne $coreAfter.Hash) { throw 'Recovered quote core changed.' }
    [ordered]@{
        version=$Version; entry=$builtEntry; sha256=(Get-FileHash -LiteralPath $builtEntry).Hash;
        current_client_unchanged=$true; config_identical=((Get-FileHash -LiteralPath (Join-Path $portable 'client_config.json')).Hash -eq (Get-FileHash -LiteralPath $config).Hash);
        quote_core_identical=$true; status='Awaiting human visual and online calculation acceptance';
        note='Local review build only. Configuration contains the existing private credentials; do not publish this directory.'
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reviewRoot 'manifest.json') -Encoding utf8
    Write-Output $builtEntry
} finally {
    $env:PYTHONPATH = $savedPythonPath
    Remove-Item Env:AI_QUOTE_BUILD_VERSION,Env:AI_QUOTE_VERSION_FILE,Env:AI_QUOTE_PREVIEW_DEPS -ErrorAction SilentlyContinue
}
