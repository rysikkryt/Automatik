export type Freshness = 'online' | 'recent' | 'stale' | 'none';

/** online: < 15 min, recent: < 24 h, stale: older. Thresholds match typical tracker send periods. */
export function freshness(t: number | null | undefined, now = Date.now()): Freshness {
  if (t === null || t === undefined || !Number.isFinite(t)) return 'none';
  const age = now - t;
  if (age < 15 * 60e3) return 'online';
  if (age < 24 * 3600e3) return 'recent';
  return 'stale';
}
