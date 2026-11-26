const text = value => String(value || '').trim().toUpperCase();
export const isJcProduct = value => ['JC', 'JC_EXP'].includes(text(value));
export function explicitJcProfile(value) {
  const code = text(value);
  if (/LUXURY|DELUXE|豪华/.test(code)) return 'LUXURY';
  if (/STANDARD|标配/.test(code)) return 'STANDARD';
  return null;
}
// User-confirmed face-price models: -1 is standard; -2 is luxury.
export function jcFaceModelProfile(value) {
  const match = text(value).match(/^JC\d+-([12])$/);
  return match ? (match[1] === '1' ? 'STANDARD' : 'LUXURY') : null;
}
export function selectedJcProfile(input) {
  return explicitJcProfile(input.jc_profile_code) || explicitJcProfile(input.variant_code)
    || jcFaceModelProfile(input.model_code);
}
export function jcCostProfile(input) {
  const explicit = explicitJcProfile(input.jc_profile_code) || explicitJcProfile(input.variant_code);
  if (explicit) return explicit;
  // Retain legacy direct cost callers; new quote normalization supplies the
  // explicit configuration and never reuses face-model suffixes as cost codes.
  if (/-1$/.test(text(input.model_code))) return 'LUXURY';
  if (/-2$/.test(text(input.model_code)) || text(input.variant_code) === 'DEFAULT') return 'STANDARD';
  return null;
}
