$ErrorActionPreference = "Stop"

$configuredPython = [string]$env:AI_QUOTE_CLIENT_PYTHON
$pythonCandidates = @(
    $configuredPython,
    "G:\gongsi\banjinxitong\desktop_client\.venv64\Scripts\python.exe"
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$pythonExe = $pythonCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $pythonExe) {
    throw "Python 3.12 x64 client environment was not found. Set AI_QUOTE_CLIENT_PYTHON to its python.exe path."
}

& $pythonExe -c "import struct,sys; assert sys.version_info[:2] == (3, 12), sys.version; assert struct.calcsize('P') * 8 == 64, 'Python must be 64-bit'; import PySide6"
if ($LASTEXITCODE -ne 0) {
    throw "Client tests require Python 3.12 x64 with PySide6: $pythonExe"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$defaultCoreRoot = Join-Path $workspaceRoot "AIQuoteDualSystem\_internal\v3_core"
if ([string]::IsNullOrWhiteSpace([string]$env:AI_QUOTE_V3_CORE_ROOT)) {
    $env:AI_QUOTE_V3_CORE_ROOT = $defaultCoreRoot
}
foreach ($requiredCoreFile in @("main.raw", "original.pyz")) {
    $requiredCorePath = Join-Path $env:AI_QUOTE_V3_CORE_ROOT $requiredCoreFile
    if (-not (Test-Path -LiteralPath $requiredCorePath -PathType Leaf)) {
        throw "Client runtime core is incomplete: $requiredCorePath"
    }
}

$testFiles = @(
    "tests/verify_analysis_product_trend.py",
    "tests/verify_analysis_product_trend_http.py",
    "tests/verify_contract_status.py",
    "tests/verify_discard_close.py",
    "tests/verify_wide_labor_workflow.py",
    "tests/verify_cost_horizontal_restore.py",
    "tests/verify_quote_batch_discount.py",
    "tests/verify_front_rear_doors.py",
    "tests/verify_attachment_unit_prices.py",
    "tests/verify_copied_attachment_names.py",
    "tests/verify_cost_selection_detail.py",
    "tests/verify_quote_version_history.py",
    "tests/verify_attachment_cost_allocation.py",
    "tests/verify_formula_attachment_allocation_ui.py",
    "tests/verify_quote_version_comparison.py",
    "tests/verify_quote_version_comparison_ui.py",
    "tests/verify_automatic_update_bridge.py",
    "tests/verify_legacy_upgrade_preparation.py",
    "tests/verify_name_login_endpoint.py",
    "tests/verify_client_update_login_startup.py",
    "tests/verify_quote_delivery.py",
    "tests/verify_order_nature.py",
    "tests/verify_quote_export_customer.py",
    "tests/verify_quote_remarks.py",
    "tests/verify_quote_remark_format.py",
    "tests/verify_confirmed_remark_rules.py",
    "tests/verify_confirmed_remark_rules_ui.py",
    "tests/verify_quote_remark_format_runtime.py",
    "tests/verify_scheme2_quote_remark.py",
    "tests/verify_cost_price_breakdown.py",
    "tests/verify_cost_price_breakdown_ui.py",
    "tests/verify_quote_management_filters.py",
    "tests/verify_name_login.py",
    "tests/verify_name_login_workflow.py",
    "tests/verify_contract_identity.py",
    "tests/verify_contract_customer_flow.py",
    "tests/verify_contract_defaults.py",
    "tests/verify_customer_profiles.py",
    "tests/verify_contract_template_sharing.py",
    "tests/verify_contract_management.py",
    "tests/verify_contract_office_preview.py",
    "tests/verify_quote_management.py",
    "tests/verify_quote_analysis.py",
    "tests/verify_quote_analysis_full_workflow.py",
    "tests/verify_client_updates.py",
    "tests/verify_lan_client_updates.py",
    "tests/verify_client_update_ui.py",
    "tests/verify_client_update_sidebar.py",
    "tests/verify_first_install_config.py",
    "tests/verify_candidate_release.py",
    "tests/verify_copied_quote_reprice.py",
    "tests/verify_scheme2_cost_copy.py",
    "tests/verify_quote_request_lifecycle.py",
    "tests/verify_quote_pause_manual_retry.py",
    "tests/verify_single_action_dock.py",
    "tests/verify_wheel_edit_guard.py",
    "tests/verify_dropdown_style.py",
    "tests/verify_company_combo.py",
    "tests/verify_customer_terminology.py",
    "tests/verify_scheme2_company_layout.py",
    "tests/verify_dialog_style.py",
    "tests/verify_attachment_add_button_style.py",
    "tests/verify_attachment_picker_search.py",
    "tests/verify_removed_diagnostic_report.py",
    "tests/verify_management_fee.py",
    "tests/verify_quote_document_progress.py",
    "tests/verify_standalone_attachments.py",
    "tests/verify_gross_net_margin.py",
    "tests/verify_manufacturing_amount.py",
    "tests/verify_manufacturing_cost_ui.py",
    "tests/verify_quick_freight_ui.py",
    "tests/verify_tax_cost_ui.py",
    "tests/verify_quote_document_feedback.py",
    "tests/verify_quote_scheme_export_registration.py",
    "tests/verify_progress_style.py",
    "tests/verify_attachment_export_snapshot.py",
    "tests/verify_attachment_summary_matched_size.py",
    "tests/verify_manual_matched_size.py",
    "tests/verify_ganged_custom_attachment_snapshot.py",
    "tests/verify_attachment_summary_reference_layout.py",
    "tests/verify_attachment_summary_unit_price.py",
    "tests/verify_attachment_summary_print.py",
    "tests/verify_ganged_cost_detail_rows.py",
    "tests/verify_cost_detail_export.py",
    "tests/verify_cost_detail_zero_factor.py",
    "tests/verify_self_made_weight.py",
    "tests/verify_quote_unit_rounding.py",
    "tests/verify_scheme2_formal_quote.py",
    "tests/verify_attachment_negative_quantity.py",
    "tests/verify_quote_scheme_center.py",
    "tests/verify_new_scheme_workspace_reset.py",
    "tests/verify_quote_scheme_reference_ui.py",
    "tests/verify_quote_scheme_restore.py",
    "tests/verify_scheme2_material_price_sidebar.py",
    "tests/verify_scheme2_cost_repricing.py",
    "tests/verify_scheme2_stainless_pricing.py",
    "tests/verify_template_cache_and_batch.py",
    "tests/verify_quote_progress_ui.py",
    "tests/verify_formula_template_incomplete_read_retry.py",
    "tests/verify_ganged_single_quote_aggregation.py",
    "tests/verify_client_health_guards.py",
    "tests/verify_quote_defaults.py",
    "tests/verify_attachment_size_rules.py",
    "tests/verify_support_plate_defaults.py",
    "tests/verify_support_plate_cost_isolation.py",
    "tests/verify_manual_dimension_forms.py",
    "tests/verify_ganged_glass_reprice.py",
    "tests/verify_attachment_catalog_addition.py",
    "tests/verify_v3_program_rules.py",
    "tests/verify_generated_formula_migration.py",
    "tests/verify_v3_layout_refresh.py",
    "tests/verify_removed_recognition_workbench.py",
    "tests/verify_recognition_dimensions.py",
    "tests/verify_native_dimension_lines.py",
    "tests/verify_recognition_dimensions_ui.py",
    "tests/verify_drawing_workflow.py",
    "tests/verify_weight_freight.py",
    "tests/verify_jp_auxiliary_weight.py",
    "tests/verify_jp_auxiliary_weight_workflow.py",
    "tests/verify_freight_output.py"
)
$savedUpdateConfig = $env:AI_QUOTE_UPDATE_CONFIG
$savedApiUrl = $env:AI_QUOTE_API_URL
$savedApiKey = $env:AI_QUOTE_API_KEY
try {
    # Never let a UI fixture fall through to the installed online connection.
    $env:AI_QUOTE_API_URL = 'http://127.0.0.1:9/api/quotes/calculate-dual'
    $env:AI_QUOTE_API_KEY = 'local-test-only'
    # Business tests must not use an enabled updater from the installed client.
    # Update-specific tests explicitly supply their own local signed fixtures.
    $env:AI_QUOTE_UPDATE_CONFIG = Join-Path $repoRoot 'packaging\update_config.example.json'
    foreach ($testFile in $testFiles) {
        & $pythonExe $testFile
        if ($LASTEXITCODE -ne 0) {
            throw "Client test failed: $testFile"
        }
    }
} finally {
    if ($null -eq $savedApiUrl) { Remove-Item Env:AI_QUOTE_API_URL -ErrorAction SilentlyContinue } else { $env:AI_QUOTE_API_URL = $savedApiUrl }
    if ($null -eq $savedApiKey) { Remove-Item Env:AI_QUOTE_API_KEY -ErrorAction SilentlyContinue } else { $env:AI_QUOTE_API_KEY = $savedApiKey }
    if ($null -eq $savedUpdateConfig) {
        Remove-Item Env:AI_QUOTE_UPDATE_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:AI_QUOTE_UPDATE_CONFIG = $savedUpdateConfig
    }
}
