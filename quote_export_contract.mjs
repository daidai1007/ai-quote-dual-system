/*
 * Small, dependency-free contract shared by the API and workbook exporter.
 * Customer-facing drawing fields are allowed through only when the desktop
 * client froze an explicit original-drawing acknowledgement snapshot.
 */

export const isDrawingSourcedQuoteItem = (item = {}) => Boolean(
  String(item.source_candidate_id || '').trim()
  || String(item.source_drawing_name || '').trim()
);

const normalizedSpecification = (value) => String(value || '')
  .trim()
  .replace(/[×xX]/g, '*')
  .replace(/\s+/g, '');

const trimmed = (value) => String(value ?? '').trim();

export const validateConfirmedQuoteSnapshot = (input) => {
  if (!input || typeof input !== 'object') throw new Error('JSON body is required');
  if (!Array.isArray(input.items) || input.items.length === 0) {
    throw new Error('items are required');
  }

  input.items.forEach((item, index) => {
    if (!item || typeof item !== 'object') {
      throw new Error(`items[${index}] must be an object`);
    }
    if (!isDrawingSourcedQuoteItem(item)) return;

    if (item.source_classification !== 'cabinet') {
      throw new Error(`items[${index}].source_classification must be cabinet`);
    }
    if (item.source_review_status !== 'confirmed') {
      throw new Error(`items[${index}].source_review_status must be confirmed`);
    }
    if (item.source_remark_review_required !== false) {
      throw new Error(`items[${index}].source_remark_review_required must be false`);
    }
    if (item.source_manual_reviewed !== true) {
      throw new Error(`items[${index}].source_manual_reviewed must be true`);
    }
    if (item.source_manual_confirmation_checked !== true) {
      throw new Error(
        `items[${index}].source_manual_confirmation_checked must be true`,
      );
    }
    if (!trimmed(item.source_manual_reviewed_at)) {
      throw new Error(`items[${index}].source_manual_reviewed_at is required`);
    }
    if (!trimmed(item.specification)) {
      throw new Error(`items[${index}].specification is required`);
    }
    if (!trimmed(item.source_specification)) {
      throw new Error(`items[${index}].source_specification is required`);
    }
    if (
      normalizedSpecification(item.specification)
      !== normalizedSpecification(item.source_specification)
    ) {
      throw new Error(
        `items[${index}].specification must match source_specification`,
      );
    }
    const dimensionPairs = [
      ['width_mm', 'source_width_mm'],
      ['height_mm', 'source_height_mm'],
      ['depth_mm', 'source_depth_mm'],
    ];
    for (const [quoteKey, sourceKey] of dimensionPairs) {
      const quoteValue = Number(item[quoteKey]);
      const sourceValue = Number(item[sourceKey]);
      if (!Number.isFinite(quoteValue) || quoteValue <= 0) {
        throw new Error(`items[${index}].${quoteKey} must be a positive number`);
      }
      if (!Number.isFinite(sourceValue) || sourceValue <= 0) {
        throw new Error(`items[${index}].${sourceKey} must be a positive number`);
      }
      if (Math.abs(quoteValue - sourceValue) > 1e-6) {
        throw new Error(`items[${index}].${quoteKey} must match ${sourceKey}`);
      }
    }
    if (!Object.hasOwn(item, 'source_reviewed_remark')) {
      throw new Error(`items[${index}].source_reviewed_remark is required`);
    }
    const confirmedRemark = trimmed(item.source_reviewed_remark);
    if (!Object.hasOwn(item, 'source_ocr_remark')) {
      throw new Error(`items[${index}].source_ocr_remark is required`);
    }
    if (trimmed(item.source_ocr_remark) !== confirmedRemark) {
      throw new Error(
        `items[${index}].source_ocr_remark must match source_reviewed_remark`,
      );
    }
    if (!Object.hasOwn(item, 'final_remark')) {
      throw new Error(`items[${index}].final_remark is required`);
    }
    if (trimmed(item.final_remark) !== confirmedRemark) {
      throw new Error(
        `items[${index}].final_remark must match source_reviewed_remark`,
      );
    }
    if (Object.hasOwn(item, 'notes') && trimmed(item.notes) !== confirmedRemark) {
      throw new Error(
        `items[${index}].notes must match source_reviewed_remark`,
      );
    }
    if (!Array.isArray(item.source_evidence_fields)) {
      throw new Error(`items[${index}].source_evidence_fields must be an array`);
    }
  });

  return input;
};
