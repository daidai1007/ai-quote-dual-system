export function normalizeDrawingContext(value) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('drawing_context must be an object');
  }
  const sourceName = String(value.source_name || '').trim();
  const pageNumber = Number(value.page_number);
  const pageCount = Number(value.page_count);
  if (!sourceName || sourceName.length > 260) {
    throw new Error('drawing_context.source_name is required and must be no longer than 260 characters');
  }
  if (!Number.isInteger(pageNumber) || !Number.isInteger(pageCount)
      || pageNumber < 1 || pageCount < 1 || pageNumber > pageCount) {
    throw new Error('drawing_context page numbers must be valid positive integers');
  }
  return { source_name: sourceName, page_number: pageNumber, page_count: pageCount };
}
