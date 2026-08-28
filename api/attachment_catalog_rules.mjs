const textField = (value, name, maximum, { required = false, fallback = '' } = {}) => {
  const text = String(value ?? fallback).replaceAll('\u0000', '').normalize('NFC').trim();
  if (required && !text) throw new Error(`${name} is required`);
  if (text.length > maximum) throw new Error(`${name} cannot exceed ${maximum} characters`);
  return text;
};

const optionalDimension = (value, name) => {
  if (value === undefined || value === null || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${name} must be a positive number`);
  return number;
};

export function normalizeCatalogAttachment(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('JSON body is required');
  if (input.price === undefined || input.price === null || input.price === '') {
    throw new Error('price is required');
  }
  const price = Number(input.price);
  if (!Number.isFinite(price) || price < 0) throw new Error('price must be a non-negative number');
  const categoryLevel1 = textField(
    input.category_level1 ?? input.attachment_category,
    'category_level1',
    120,
    { fallback: '其他附件' },
  ) || '其他附件';
  return {
    attachment_category: categoryLevel1,
    category_level1: categoryLevel1,
    category_level2: textField(input.category_level2, 'category_level2', 120),
    category_level3: textField(input.category_level3, 'category_level3', 120),
    item_name: textField(input.item_name, 'item_name', 160, { required: true }),
    model_code: textField(input.model_code, 'model_code', 100) || null,
    variant: textField(input.variant, 'variant', 80) || null,
    width_mm: optionalDimension(input.width_mm, 'width_mm'),
    height_mm: optionalDimension(input.height_mm, 'height_mm'),
    depth_mm: optionalDimension(input.depth_mm, 'depth_mm'),
    price,
    price_text: textField(input.price_text, 'price_text', 120, { fallback: String(price) }),
    unit: textField(input.unit, 'unit', 20, { fallback: '元' }),
    price_source: textField(input.price_source, 'price_source', 40, { fallback: '人工新增' }),
    notes: textField(input.notes, 'notes', 2000) || null,
  };
}
