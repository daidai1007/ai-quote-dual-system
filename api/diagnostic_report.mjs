import {randomUUID} from 'node:crypto';

export const MAX_DIAGNOSTIC_BYTES = 4 * 1024 * 1024;
const forbiddenKeys = [
  'password', 'secret', 'token', 'api_key', 'authorization', 'database_url',
  'source_path', 'file_path', 'local_path', 'source_pdf_name', 'drawing_context',
  'image_data', 'raw_pdf', 'pdf_bytes', 'base64',
];
const textSql = value => `convert_from(decode('${Buffer.from(String(value), 'utf8').toString('hex')}', 'hex'), 'UTF8')`;

function clean(value, depth = 0) {
  if (depth > 10) return '[层级已截断]';
  if (Array.isArray(value)) return value.slice(0, 500).map(item => clean(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).slice(0, 300)
      .filter(([key]) => !forbiddenKeys.some(marker => key.toLowerCase().includes(marker)))
      .map(([key, item]) => [key.slice(0, 80), clean(item, depth + 1)]));
  }
  if (typeof value === 'string') {
    const redacted = value
      .replace(/\b(api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+/gi, '$1=[已隐藏]')
      .replace(/(^|\W)[a-zA-Z]:[\\/][^\s"'，；,;]+/g, '$1[本地路径已隐藏]');
    return (/^[a-zA-Z]:[\\/]|^\\\\|^\/(?:home|Users|tmp)\//.test(redacted)
      ? '[本地路径已隐藏]' : redacted.slice(0, 1000));
  }
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  return value === null || typeof value === 'boolean' ? value : String(value).slice(0, 1000);
}

export function validateDiagnosticSubmission(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || input.confirmed_by_operator !== true) {
    throw Object.assign(new Error('operator confirmation is required'), {statusCode: 400});
  }
  const report = input.report;
  if (!report || typeof report !== 'object' || Array.isArray(report)
      || !Array.isArray(report.quote_items) || !Array.isArray(report.events)) {
    throw Object.assign(new Error('report must contain quote_items and events'), {statusCode: 400});
  }
  if (report.quote_items.length > 200 || report.events.length > 200) {
    throw Object.assign(new Error('too many diagnostic rows or events'), {statusCode: 400});
  }
  const sanitized = clean({
    schema_version: report.schema_version,
    created_at: report.created_at,
    client_version: report.client_version,
    order_number: report.order_number,
    company_name: report.company_name,
    issue_description: report.issue_description,
    operator_name: report.operator_name,
    current_selection: report.current_selection,
    quote_items: report.quote_items,
    events: report.events,
    last_request_id: report.last_request_id,
  });
  const bytes = Buffer.byteLength(JSON.stringify(sanitized), 'utf8');
  if (bytes > MAX_DIAGNOSTIC_BYTES) {
    throw Object.assign(new Error('diagnostic report is too large'), {statusCode: 413});
  }
  return sanitized;
}

export function diagnosticReportSql(report, reportId = randomUUID()) {
  const json = JSON.stringify(report);
  return `BEGIN;
DELETE FROM calc.client_diagnostic_report WHERE submitted_at < now() - interval '90 days';
INSERT INTO calc.client_diagnostic_report (report_id, client_version, order_number, report_payload)
VALUES ('${reportId}'::uuid, ${textSql(report.client_version || '')},
  ${textSql(report.order_number || '')}, ${textSql(json)}::jsonb)
RETURNING jsonb_build_object('submitted', TRUE, 'report_id', report_id, 'submitted_at', submitted_at)::text;
COMMIT;`;
}
