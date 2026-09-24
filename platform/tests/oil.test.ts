import { describe, expect, it } from 'vitest';
import { analyzeLevel, sensorStatus } from '../server/domain/sensors.js';

function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}
function gauss(r: () => number) {
  return Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
}

describe('oil level analysis under sump noise', () => {
  it('recovers consumption and top-ups with ±1.5 pp noise, no false top-ups', () => {
    for (const seed of [1, 2, 3, 4, 5]) {
      const r = rng(seed);
      const t0 = Date.UTC(2026, 8, 1);
      const level: Array<{ t: number; v: number }> = [];
      const hours: Array<{ t: number; v: number }> = [];
      // 100 engine hours, a reading every 30 min of operation; 0.25 pp/h; top-ups at 35 h and 70 h (+18 pp)
      for (let i = 0; i <= 200; i++) {
        const h = i / 2;
        const t = t0 + i * 1800e3;
        const truth = 85 - 0.25 * h + (h >= 35 ? 18 : 0) + (h >= 70 ? 18 : 0);
        level.push({ t, v: truth + 1.5 * gauss(r) });
        hours.push({ t, v: 3000 + h });
      }
      const a = analyzeLevel(level, hours);
      expect(a.topups).toHaveLength(2);
      for (const tp of a.topups) expect(tp.to - tp.from).toBeGreaterThan(16);
      expect(a.consumption_pct_per_100h!).toBeGreaterThan(25 * 0.9);
      expect(a.consumption_pct_per_100h!).toBeLessThan(25 * 1.1);
    }
  });

  it('flat noisy level: no top-ups, consumption ≈ 0', () => {
    const r = rng(9);
    const pts = Array.from({ length: 120 }, (_, i) => ({ t: i * 3600e3, v: 70 + 1.5 * gauss(r) }));
    const hs = pts.map((p, i) => ({ t: p.t, v: i }));
    const a = analyzeLevel(pts, hs);
    expect(a.topups).toHaveLength(0);
    expect(a.consumption_pct_per_100h!).toBeLessThan(1.5);
  });

  it('reference limits', () => {
    expect(sensorStatus('oil_level_pct', 12)).toBe('crit');
    expect(sensorStatus('oil_level_pct', 20)).toBe('warn');
    expect(sensorStatus('oil_water_aw', 0.3)).toBe('ok');
    expect(sensorStatus('oil_level_low', 1)).toBe('crit');
    expect(sensorStatus('oil_pressure_kpa', 300)).toBeNull();
  });
});
