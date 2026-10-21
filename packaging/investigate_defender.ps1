param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$DefenderExe = 'C:\ProgramData\Microsoft\Windows Defender\Platform\4.18.26090.9-0\MpCmdRun.exe'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $repo
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $output.StartsWith(([IO.Path]::GetFullPath((Join-Path $repo 'outputs')) + '\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Investigation output must be under repository outputs.'
}
if (Test-Path -LiteralPath $output) { throw 'Use a fresh investigation output directory.' }
if ((Get-AuthenticodeSignature -LiteralPath $DefenderExe).Status -ne 'Valid') { throw 'Defender CLI signature is not valid.' }
$before = Get-MpComputerStatus
if (-not $before.AntivirusEnabled -or -not $before.RealTimeProtectionEnabled) { throw 'Defender protection must remain enabled.' }
New-Item -ItemType Directory -Path $output | Out-Null
$preferenceBefore = Get-MpPreference | Select-Object DisableRealtimeMonitoring,ExclusionPath,ExclusionProcess,ExclusionExtension,SubmitSamplesConsent,MAPSReporting
$stage = Join-Path $workspace 'AIQuoteDualSystem_Installer\2026.10.20.05-FirstInstall\stage'
$items = @(
    @{ label='01-client-exe'; path=(Join-Path $stage 'AIQuoteDualSystem_layout_v0.exe') },
    @{ label='02-internal-dependencies'; path=(Join-Path $stage '_internal') },
    @{ label='03-pdf-runtime'; path=(Join-Path $stage 'runtime') },
    @{ label='04-complete-unpacked-payload'; path=$stage },
    @{ label='05-original-installer'; path=(Join-Path $workspace 'AIQuoteDualSystem_Installer\2026.10.20.05-FirstInstall\AIQuoteDualSystem_Setup_v2026.10.20.05.exe') },
    @{ label='06-nsis-compiler'; path=(Join-Path $workspace '.installer-tools\nsis-3.12\nsis-3.12\makensis.exe') },
    @{ label='07-nsis-stubs-and-plugins'; path=(Join-Path $workspace '.installer-tools\nsis-3.12\nsis-3.12') },
    @{ label='08-nsis-original-archive'; path=(Join-Path $workspace '.installer-tools\nsis-3.12.zip') }
)
$results = @()
foreach ($item in $items) {
    Write-Output ('Scanning ' + $item.label)
    if (-not (Test-Path -LiteralPath $item.path)) {
        $results += [ordered]@{ label=$item.label; path=$item.path; status='missing_or_quarantined'; exit_code=$null }
        continue
    }
    $scanStatus = Get-MpComputerStatus
    $scanOutput = & $DefenderExe -Scan -ScanType 3 -File $item.path -DisableRemediation 2>&1
    $scanExit = $LASTEXITCODE
    # Documented forensic mode: scan archives, ignore exclusions, report threats,
    # and do not restore/quarantine/remove user files. Real-time protection stays on.
    $scanOutput | Out-File -LiteralPath (Join-Path $output ($item.label + '.log')) -Encoding utf8
    $text = $scanOutput -join [Environment]::NewLine
    $noThreats = $scanExit -eq 0 -and $text -match 'found no threats'
    $results += [ordered]@{
        label=$item.label; path=$item.path; exit_code=$scanExit;
        status=$(if ($noThreats) { 'no_threats_detected' } else { 'requires_review' });
        signature_version=$scanStatus.AntivirusSignatureVersion
    }
    $results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output 'scan-results.json') -Encoding utf8
    Write-Output ($item.label + ': exit=' + $scanExit + '; no_threats=' + $noThreats)
}
$after = Get-MpComputerStatus
$preferenceAfter = Get-MpPreference | Select-Object DisableRealtimeMonitoring,ExclusionPath,ExclusionProcess,ExclusionExtension,SubmitSamplesConsent,MAPSReporting
if (($preferenceBefore | ConvertTo-Json -Depth 5 -Compress) -ne ($preferenceAfter | ConvertTo-Json -Depth 5 -Compress)) {
    throw 'Protection or sample/exclusion settings changed during the investigation; review independently.'
}
$report = [ordered]@{
    antivirus_enabled_before=$before.AntivirusEnabled;
    realtime_enabled_before=$before.RealTimeProtectionEnabled;
    antivirus_enabled_after=$after.AntivirusEnabled;
    realtime_enabled_after=$after.RealTimeProtectionEnabled;
    exclusions_and_protection_settings_unchanged=$true;
    quarantined_items_restored=$false;
    manual_sample_upload_performed=$false;
    scan_mode='Microsoft-documented custom forensic scan; no remediation; archive scanning; exclusions ignored';
    results=$results
}
$report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $output 'investigation.json') -Encoding utf8
$report | ConvertTo-Json -Depth 7
