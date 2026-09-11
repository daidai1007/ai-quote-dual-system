param([string]$PostgresBin = 'G:/PostgreSQL/18/bin')
$ErrorActionPreference = 'Stop'
$attachmentRepo = Split-Path -Parent $PSScriptRoot
$attachmentWork = Join-Path $attachmentRepo 'test-output/attachment-cost-v2'
$attachmentData = Join-Path $attachmentWork 'pgdata'
New-Item -ItemType Directory -Path $attachmentWork -Force | Out-Null
$attachmentPsql = Join-Path $PostgresBin 'psql.exe'
$attachmentNode = (Get-Command node).Source
$attachmentStarted = $false
try {
  if (-not (Test-Path -LiteralPath (Join-Path $attachmentData 'PG_VERSION'))) {
    & (Join-Path $PostgresBin 'initdb.exe') -D $attachmentData -U attachment_test -A trust --encoding=UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { throw 'Isolated test database initialization failed' }
  }
  & (Join-Path $PostgresBin 'pg_isready.exe') -h 127.0.0.1 -p 55439 | Out-Null
  if ($LASTEXITCODE -ne 0) {
    $attachmentProcess = Start-Process -FilePath (Join-Path $PostgresBin 'postgres.exe') -ArgumentList @('-D',('"' + $attachmentData + '"'),'-h','127.0.0.1','-p','55439') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $attachmentWork 'runner.stdout.log') -RedirectStandardError (Join-Path $attachmentWork 'runner.stderr.log')
    $attachmentStarted = $true
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
      & (Join-Path $PostgresBin 'pg_isready.exe') -h 127.0.0.1 -p 55439 | Out-Null
      if ($LASTEXITCODE -eq 0) { break }
      Start-Sleep -Milliseconds 200
    }
  }
  # Compare cluster identifiers, avoiding Windows GBK/UTF-8 path display differences.
  $actualIdentifier = & $attachmentPsql -X -w -h 127.0.0.1 -p 55439 -U attachment_test -d postgres -At -c 'SELECT system_identifier FROM pg_control_system();'
  if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect isolated database identity' }
  $controlInfo = & (Join-Path $PostgresBin 'pg_controldata.exe') -D $attachmentData
  $expectedIdentifier = (($controlInfo | Where-Object { $_ -match '^Database system identifier:' }) -split ':',2)[1].Trim()
  if ($actualIdentifier.Trim() -ne $expectedIdentifier) { throw 'Port 55439 is not the expected isolated test cluster' }
  $env:ATTACHMENT_TEST_PSQL = $attachmentPsql
  & $attachmentNode --test --test-concurrency=1 (Join-Path $attachmentRepo 'tests/attachment_cost_v2.test.mjs') (Join-Path $attachmentRepo 'tests/attachment_v2_database.test.mjs') (Join-Path $attachmentRepo 'tests/cabinet_material_service.test.mjs') (Join-Path $attachmentRepo 'tests/cabinet_material_database.test.mjs') 2>&1 | Tee-Object -FilePath (Join-Path $attachmentWork 'validation.log')
  if ($LASTEXITCODE -ne 0) { throw 'Attachment tests failed; see validation.log' }
} finally {
  if ($attachmentStarted) {
    & (Join-Path $PostgresBin 'pg_ctl.exe') -D $attachmentData -m fast -w stop
  }
}
