param(
    [Parameter(Mandatory=$true)][string]$ScanPath,
    [Parameter(Mandatory=$true)][string]$ReportDirectory
)
$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $ScanPath).Path
$report = [IO.Path]::GetFullPath($ReportDirectory)
if (Test-Path -LiteralPath $report) { throw 'Use a fresh Defender scan report directory.' }
$platform = Get-ChildItem -LiteralPath (Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform') -Directory |
    Where-Object Name -Match '^\d+\.\d+\.\d+\.\d+-\d+$' | Sort-Object Name -Descending | Select-Object -First 1
if (-not $platform) { throw 'Microsoft Defender platform was not found; release is not approved.' }
$scanner = Join-Path $platform.FullName 'MpCmdRun.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $scanner
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw 'The Defender scanner must have a valid Microsoft signature.'
}
$before = Get-MpComputerStatus
if (-not $before.AntivirusEnabled -or -not $before.RealTimeProtectionEnabled) {
    throw 'Antivirus and real-time protection must remain enabled; release is not approved.'
}
$preferenceBefore = Get-MpPreference | Select-Object DisableRealtimeMonitoring,ExclusionPath,ExclusionProcess,ExclusionExtension,SubmitSamplesConsent,MAPSReporting
New-Item -ItemType Directory -Path $report | Out-Null
$scans = @()
foreach ($mode in @('archive-aware-forensic','normal-custom')) {
    $arguments = @('-Scan','-ScanType','3','-File',$target)
    if ($mode -eq 'archive-aware-forensic') { $arguments += '-DisableRemediation' }
    # Microsoft documents that forensic mode scans archives and ignores exclusions.
    # It changes no settings and merely retains evidence if detection occurs.
    $scanOutput = & $scanner @arguments 2>&1
    $scanExit = $LASTEXITCODE
    $scanOutput | Out-File -LiteralPath (Join-Path $report ($mode + '.log')) -Encoding utf8
    $text = $scanOutput -join [Environment]::NewLine
    $clear = $scanExit -eq 0 -and $text -match 'found no threats'
    $scans += [ordered]@{ mode=$mode; exit_code=$scanExit; no_threats_detected=$clear }
    if (-not $clear) {
        $scans | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $report 'failed-scans.json') -Encoding utf8
        throw ('Defender did not clear the release: ' + $target + '; mode=' + $mode + '; exit=' + $scanExit)
    }
}
$after = Get-MpComputerStatus
$preferenceAfter = Get-MpPreference | Select-Object DisableRealtimeMonitoring,ExclusionPath,ExclusionProcess,ExclusionExtension,SubmitSamplesConsent,MAPSReporting
$unchanged = ($preferenceBefore | ConvertTo-Json -Depth 5 -Compress) -eq ($preferenceAfter | ConvertTo-Json -Depth 5 -Compress)
if (-not $unchanged -or -not $after.AntivirusEnabled -or -not $after.RealTimeProtectionEnabled) {
    throw 'Protection/exclusion settings changed during scan; release is not approved.'
}
$result = [ordered]@{
    target=$target; scanned_at_utc=(Get-Date).ToUniversalTime().ToString('o');
    scanner=$scanner; scanner_signature='Valid Microsoft';
    signature_version_before=$before.AntivirusSignatureVersion;
    signature_version_after=$after.AntivirusSignatureVersion;
    antivirus_enabled=$after.AntivirusEnabled;
    realtime_protection_enabled=$after.RealTimeProtectionEnabled;
    protection_and_exclusion_settings_unchanged=$unchanged;
    manual_sample_upload_performed=$false; quarantine_restored=$false;
    scans=$scans; result='no_threats_detected';
    limitation='No detection with these signatures is not an absolute safety guarantee or a vendor false-positive determination.'
}
$result | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $report 'scan-result.json') -Encoding utf8
Write-Output ('DEFENDER_RELEASE_SCAN=PASS; signatures=' + $after.AntivirusSignatureVersion)
