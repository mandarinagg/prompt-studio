/** Redondea al múltiplo de `step` más cercano, sin restos de coma flotante (0.30000000000000004). */
export function snap(value: number, step: number): number {
  const decimals = Math.max(0, Math.ceil(-Math.log10(step)));
  return Number((Math.round(value / step) * step).toFixed(decimals));
}

/** Lo que el usuario escribe en un campo numérico (acepta coma decimal), dentro del rango. */
export function parseNumber(text: string, min: number, max: number): number | null {
  const t = text.trim().replace(",", ".");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
  return Math.min(max, Math.max(min, Number(t)));
}
