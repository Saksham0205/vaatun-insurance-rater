const NAMES: Record<string, string> = {
  godigit: 'Go Digit',
  'hdfc-ergo': 'HDFC ERGO',
  'reliance-indusind': 'Reliance General',
  'tata-aig': 'Tata AIG',
};

/** Display name for an insurer key from the rating engine (e.g. `hdfc-ergo` → `HDFC ERGO`). */
export function insurerName(key: string | null | undefined): string {
  if (!key) return '';
  return NAMES[key] ?? key;
}
