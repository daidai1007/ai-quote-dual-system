param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbookPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$excel = $null
$workbook = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $workbook = $excel.Workbooks.Open($WorkbookPath, 0, $true)

    $families = @(
        @{ family = 'JS'; sheet = 'JS'; single = 'B17'; double = 'B11'; weight = 'H28'; area = 'N28'; doors = $true },
        @{ family = 'JP'; sheet = 'JP'; single = 'B24'; double = 'B11'; weight = 'H29'; area = 'N29'; doors = $true },
        @{ family = 'JA'; sheet = 'JA'; single = 'B16'; double = 'B17'; weight = 'H28'; area = 'N28'; doors = $true },
        @{ family = 'JE'; sheet = 'JE'; single = 'B16'; double = 'B17'; weight = 'H28'; area = 'N28'; doors = $true },
        @{ family = 'JK'; sheet = 'JK'; weight = 'H26'; area = 'N26'; doors = $false },
        @{ family = 'JM'; sheet = 'JM'; weight = 'H28'; area = 'N28'; doors = $false }
    )
    $dimensions = @(
        @{ label = '600x600x2000'; width = 600; depth = 600; height = 2000 },
        @{ label = '800x1800x300'; width = 800; depth = 1800; height = 300 }
    )
    $doorCombinations = @(
        @{ single = 1; double = 0 },
        @{ single = 2; double = 0 },
        @{ single = 0; double = 1 },
        @{ single = 0; double = 2 },
        @{ single = 1; double = 1 }
    )
    $results = [System.Collections.Generic.List[object]]::new()

    foreach ($dimension in $dimensions) {
        foreach ($family in $families) {
            $sheet = $workbook.Worksheets.Item($family.sheet)
            $sheet.Range('B6').Value2 = $dimension.width
            $sheet.Range('B7').Value2 = $dimension.height
            $sheet.Range('B8').Value2 = $dimension.depth
            $cases = if ($family.doors) { $doorCombinations } else { @(@{ single = 1; double = 0 }) }
            foreach ($door in $cases) {
                if ($family.doors) {
                    $sheet.Range($family.single).Value2 = $door.single
                    $sheet.Range($family.double).Value2 = $door.double
                }
                $excel.CalculateFullRebuild()
                $results.Add([pscustomobject]@{
                    dimension = $dimension.label
                    width_mm = $dimension.width
                    depth_mm = $dimension.depth
                    height_mm = $dimension.height
                    family = $family.family
                    doors = if ($family.doors) { "$( $door.single )/$( $door.double )" } else { '-' }
                    weight_kg = [double]$sheet.Range($family.weight).Value2
                    area_m2 = [double]$sheet.Range($family.area).Value2
                    display_weight_kg = [math]::Round([double]$sheet.Range($family.weight).Value2, 1)
                    display_area_m2 = [math]::Round([double]$sheet.Range($family.area).Value2, 1)
                })
            }
        }
    }

    $payload = [pscustomobject]@{
        source_workbook = $WorkbookPath
        calculation_engine = 'Microsoft Excel CalculateFullRebuild'
        case_count = $results.Count
        results = $results
    }
    $json = $payload | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($OutputPath, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Output "EXCEL_ORACLE_CASES=$($results.Count)"
    Write-Output "EXCEL_ORACLE_OUTPUT=$OutputPath"
}
finally {
    if ($workbook -ne $null) {
        $workbook.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
    }
    if ($excel -ne $null) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
