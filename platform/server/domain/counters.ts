/**
 * Engine-hour and odometer fusion.
 *
 * Sources report counters of different nature: the ECU value (absolute, equals the dashboard
 * meter), tracker/platform counters (exact increments, arbitrary start value), and our phone
 * detector (estimated increments). Dashboard meter readings are the ground truth: they fix the
 * offset of relative counters and the scale of estimated ones. Every displayed value keeps its
 * method and timestamp so an estimate is never shown as a measurement.
 */

export type CounterMethod = 'ecu' | 'tracker' | 'platform' | 'device' | 'reading';

export interface Point {
  t: number;
  value: number;
}

export interface Calibration {
  scale: number;
  offset: number;
  n: number;
  maxResidual: number | null;
  basis: string;
}

export const EXACT_METHODS: ReadonlySet<CounterMethod> = new Set(['ecu', 'tracker', 'platform', 'reading']);

/** Raw source value at time t by linear interpolation; null if t is not bracketed closely enough. */
export function valueAt(points: Point[], t: number, maxGapMs = 36 * 3600e3): number | null {
  if (points.length === 0) return null;
  let lo = 0;
  let hi = points.length - 1;
  if (t < points[0].t || t > points[hi].t) {
    const edge = t < points[0].t ? points[0] : points[hi];
    // a reading taken right before/after the first/last sample (engine off in between)
    return Math.abs(edge.t - t) <= 15 * 60e3 ? edge.value : null;
  }
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t <= t) lo = mid;
    else hi = mid;
  }
  const a = points[lo];
  const b = points[hi];
  if (b.t === a.t) return a.value;
  if (b.t - a.t > maxGapMs && b.value !== a.value) return null;
  return a.value + ((b.value - a.value) * (t - a.t)) / (b.t - a.t);
}

/**
 * Fit displayed = raw*scale + offset from meter readings.
 * Exact-increment sources (tracker/platform): scale is fixed at 1, offset = median residual.
 * Estimated sources (device): least-squares scale+offset once two readings span >= 5 raw units.
 */
export function fitCalibration(points: Point[], readings: Point[], method: CounterMethod): Calibration | null {
  const pairs: Array<[number, number]> = [];
  for (const r of readings) {
    const raw = valueAt(points, r.t);
    if (raw !== null) pairs.push([raw, r.value]);
  }
  if (pairs.length === 0) return null;
  let scale = 1;
  let offset: number;
  if (method === 'device' && pairs.length >= 2) {
    const xs = pairs.map((p) => p[0]);
    const span = Math.max(...xs) - Math.min(...xs);
    if (span >= 5) {
      const n = pairs.length;
      const mx = xs.reduce((s, x) => s + x, 0) / n;
      const my = pairs.reduce((s, p) => s + p[1], 0) / n;
      let sxy = 0;
      let sxx = 0;
      for (const [x, y] of pairs) {
        sxy += (x - mx) * (y - my);
        sxx += (x - mx) ** 2;
      }
      scale = sxx > 0 ? sxy / sxx : 1;
      // a detector can miss or over-count, but not by a factor of two
      scale = Math.min(1.5, Math.max(0.67, scale));
      offset = my - scale * mx;
    } else {
      offset = median(pairs.map(([x, y]) => y - x));
    }
  } else {
    offset = median(pairs.map(([x, y]) => y - x));
  }
  const residuals = pairs.map(([x, y]) => Math.abs(y - (x * scale + offset)));
  return {
    scale,
    offset,
    n: pairs.length,
    maxResidual: pairs.length > 1 ? Math.max(...residuals) : null,
    basis: `${pairs.length} показани${pairs.length === 1 ? 'е' : pairs.length < 5 ? 'я' : 'й'} счётчика`,
  };
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export interface Candidate {
  value: number;
  t: number;
  method: CounterMethod;
  sourceId?: string;
  calibrated: boolean;
}

export interface Best {
  value: number;
  t: number;
  method: CounterMethod;
  sourceId?: string;
  exact: boolean;
  calibrated: boolean;
  lastExact: Candidate | null;
}

const RANK: Record<CounterMethod, number> = { ecu: 4, reading: 3, platform: 2, tracker: 2, device: 1 };

/**
 * Pick the value to display: the freshest exact value; an estimate is shown only when it is newer
 * than every exact value (and then flagged). Ties within 10 minutes go to the more direct method.
 */
export function pickBest(cands: Candidate[]): Best | null {
  if (cands.length === 0) return null;
  const exact = cands.filter((c) => EXACT_METHODS.has(c.method));
  const lastExact = exact.reduce<Candidate | null>((best, c) => {
    if (!best) return c;
    if (Math.abs(c.t - best.t) <= 10 * 60e3) return RANK[c.method] > RANK[best.method] ? c : best;
    return c.t > best.t ? c : best;
  }, null);
  const estimates = cands.filter((c) => c.method === 'device');
  const lastEst = estimates.reduce<Candidate | null>((b, c) => (!b || c.t > b.t ? c : b), null);
  if (lastEst && (!lastExact || lastEst.t > lastExact.t + 60e3)) {
    return { ...lastEst, exact: false, lastExact };
  }
  if (!lastExact) return null;
  return { ...lastExact, exact: true, lastExact };
}
