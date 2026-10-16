import assert from 'node:assert/strict';
import test from 'node:test';
import {diagnosticReportSql, validateDiagnosticSubmission} from '../api/diagnostic_report.mjs';

test('diagnostic report requires explicit confirmation and preserves quote detail', () => {
  const input = {confirmed_by_operator: true, report: {
    schema_version: 1, client_version: '2026.10.16.01', order_number: 'ORDER-1',
    issue_description: '修改附件后导出金额不一致', operator_name: '张工',
    quote_items: [{product_code: 'JM', model_code: 'JM-1200', specification: '1200*400*1400',
      quantity: 2, formula: {material_cost: 473.98, api_key: 'do-not-store'},
      attachments: [{item_name: '风机', quantity: 4, unit_price: 120}],
      source_path: 'C:\\private\\drawing.pdf', final_remark: 'api_key=hidden-value'}],
    events: [{action: 'quote_calculation_completed', details: {
      request_id: 'req-123', message: '无法读取 C:\\private\\drawing.pdf'}}],
  }};
  assert.throws(() => validateDiagnosticSubmission({...input, confirmed_by_operator: false}), /confirmation/);
  const report = validateDiagnosticSubmission(input);
  assert.equal(report.quote_items[0].model_code, 'JM-1200');
  assert.equal(report.issue_description, '修改附件后导出金额不一致');
  assert.equal(report.operator_name, '张工');
  assert.equal(report.quote_items[0].attachments[0].unit_price, 120);
  assert.equal(report.quote_items[0].formula.material_cost, 473.98);
  assert.equal(report.quote_items[0].source_path, undefined);
  assert.equal(report.quote_items[0].formula.api_key, undefined);
  assert.equal(report.quote_items[0].final_remark, 'api_key=[已隐藏]');
  assert.doesNotMatch(report.events[0].details.message, /private|drawing\.pdf/);
  const sql = diagnosticReportSql(report, '11111111-1111-4111-8111-111111111111');
  assert.match(sql, /INSERT INTO calc\.client_diagnostic_report/);
  assert.match(sql, /90 days/);
  assert.doesNotMatch(sql, /do-not-store|private\\drawing/);
});

test('diagnostic report rejects unbounded payloads', () => {
  assert.throws(() => validateDiagnosticSubmission({confirmed_by_operator: true,
    report: {quote_items: Array.from({length: 201}, () => ({})), events: []}}), /too many/);
});
