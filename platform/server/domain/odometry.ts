import { haversineM, validLatLon } from './geo.js';

/**
 * Robust GNSS odometry for any machine class.
 *
 * Naive summing of distances between consecutive fixes grows without bound on a machine that
 * stands still (receiver noise, multipath under canopy) or whose antenna sits on a rotating upper
 * structure (excavators, crawler cranes, excavator-based harvesters: every swing draws an arc).
 * The algorithm below counts only displacement that is larger than the position uncertainty and
 * the antenna swing radius, integrates Doppler speed when dense fixes are available, and books
 * movement faster than the machine can drive itself as transport (lowboy trailer), not mileage.
 * Validation: scripts/odometry_validation.py (simulated classes + real tractor GNSS data).
 */

export interface Fix {
  t: number; // epoch ms
  lat: number;
  lon: number;
  speedKmh?: number | null;
  hdop?: number | null;
  sats?: number | null;
  accM?: number | null;
}

export interface MachineProfile {
  chassis: 'wheeled' | 'tracked';
  rotatingUpper: boolean;
  category?: string;
}

export interface OdoParams {
  selfVmaxKmh: number;
  outlierVmaxKmh: number;
  minMoveKmh: number;
  baseRadiusM: number;
  uereM: number;
  kSigma: number;
  kSigmaMoving: number;
  kSigmaMovingSparse: number;
  sparseDtS: number;
  moveRule: 'any' | 'both';
  denseMaxDtS: number;
  maxHdop: number;
  minSats: number;
  maxAccM: number;
  defaultSigmaM: number;
}

// Highest speed the machine reaches under its own power (km/h), with margin.
const SELF_VMAX: Record<string, number> = {
  harvester: 35,
  forwarder: 35,
  skidder: 40,
  combine: 45,
  forage_harvester: 45,
  tractor: 70,
  sprayer: 60,
  loader: 50,
  telehandler: 45,
  grader: 50,
  roller: 20,
  excavator: 40, // wheeled excavators; tracked ones get 15 below
  crane: 90,
  dump_truck: 70, // off-highway haul trucks
  truck: 130,
  timber_truck: 130,
  dozer: 15,
  drill: 10,
};

const FORESTRY = new Set(['harvester', 'forwarder', 'skidder']);

export function paramsFor(p: MachineProfile): OdoParams {
  const cat = p.category ?? '';
  let selfV = SELF_VMAX[cat] ?? (p.chassis === 'tracked' ? 15 : 130);
  if (p.chassis === 'tracked') selfV = Math.min(selfV, 15);
  return {
    selfVmaxKmh: selfV,
    outlierVmaxKmh: Math.max(250, selfV * 3),
    minMoveKmh: p.chassis === 'tracked' || FORESTRY.has(cat) ? 0.8 : 1.5,
    // antenna on a rotating upper structure: swing radius 1.5–3.5 m, arc chord up to 7 m
    baseRadiusM: p.rotatingUpper ? 12 : p.chassis === 'tracked' ? 8 : 6,
    uereM: 4.5,
    kSigma: 3,
    // Doppler speed says the machine moved: independent evidence allows a tighter radius.
    // Chosen by sweep (scripts/odometry_validation.py): dense tracks need more margin against
    // speed noise than tracks with fixes minutes apart.
    kSigmaMoving: 2.5,
    kSigmaMovingSparse: 1.5,
    sparseDtS: 120,
    moveRule: 'any',
    denseMaxDtS: 5,
    maxHdop: 8,
    minSats: 4,
    maxAccM: 60,
    defaultSigmaM: 5,
  };
}

export interface OdoResult {
  km: number;
  transportKm: number;
  used: number;
  rejected: number;
  outliers: number;
}

function sigmaOf(f: Fix, p: OdoParams): number {
  if (typeof f.accM === 'number' && f.accM > 0) return f.accM;
  if (typeof f.hdop === 'number' && f.hdop > 0) return Math.max(1.5, f.hdop * p.uereM);
  return p.defaultSigmaM;
}

export function isUsableFix(f: Fix, p: OdoParams): boolean {
  if (!Number.isFinite(f.t) || !validLatLon(f.lat, f.lon)) return false;
  if (typeof f.sats === 'number' && f.sats > 0 && f.sats < p.minSats) return false;
  if (typeof f.hdop === 'number' && f.hdop > p.maxHdop) return false;
  if (typeof f.accM === 'number' && f.accM > p.maxAccM) return false;
  return true;
}

export function robustDistance(fixesIn: Fix[], profile: MachineProfile, override?: Partial<OdoParams>): OdoResult {
  const p = { ...paramsFor(profile), ...override };
  const fixes = fixesIn.filter((f) => isUsableFix(f, p)).sort((a, b) => a.t - b.t);
  const res: OdoResult = { km: 0, transportKm: 0, used: 0, rejected: fixesIn.length - fixes.length, outliers: 0 };
  if (fixes.length === 0) return res;

  let anchor = fixes[0];
  let anchorSigma = sigmaOf(anchor, p);
  let last = fixes[0];
  let pending: Fix | null = null;
  res.used = 1;

  for (let i = 1; i < fixes.length; i++) {
    const f = fixes[i];
    const dt = (f.t - last.t) / 1000;
    if (dt <= 0) continue;
    const dLast = haversineM(last.lat, last.lon, f.lat, f.lon);
    const vImplied = (dLast / dt) * 3.6;

    if (vImplied > p.outlierVmaxKmh && dt < 600) {
      // A single wild fix is an outlier; two consistent fixes far away mean a real relocation
      // (e.g. power-up after transport) that we cannot attribute to own driving.
      if (pending && haversineM(pending.lat, pending.lon, f.lat, f.lon) < 3 * Math.max(sigmaOf(f, p), 10)) {
        res.transportKm += haversineM(last.lat, last.lon, f.lat, f.lon) / 1000;
        anchor = f;
        anchorSigma = sigmaOf(f, p);
        last = f;
        pending = null;
        res.used++;
      } else {
        pending = f;
        res.outliers++;
      }
      continue;
    }
    pending = null;
    res.used++;

    const speedTransport =
      typeof f.speedKmh === 'number' &&
      typeof last.speedKmh === 'number' &&
      f.speedKmh > p.selfVmaxKmh * 1.15 &&
      last.speedKmh > p.selfVmaxKmh * 1.15;
    if (speedTransport || (vImplied > p.selfVmaxKmh * 1.25 && dLast > 3 * p.baseRadiusM)) {
      res.transportKm += dLast / 1000;
      anchor = f;
      anchorSigma = sigmaOf(f, p);
      last = f;
      continue;
    }

    const dense = dt <= p.denseMaxDtS && typeof f.speedKmh === 'number' && typeof last.speedKmh === 'number';
    if (dense && !profile.rotatingUpper) {
      // Doppler speed is far less noisy than position differences; integrate it while moving.
      if ((f.speedKmh as number) >= p.minMoveKmh && (last.speedKmh as number) >= p.minMoveKmh) {
        res.km += (((f.speedKmh as number) + (last.speedKmh as number)) / 2 / 3.6) * dt / 1000;
        anchor = f;
        anchorSigma = sigmaOf(f, p);
      }
      last = f;
      continue;
    }

    const sf = sigmaOf(f, p);
    const dA = haversineM(anchor.lat, anchor.lon, f.lat, f.lon);
    // a swinging cab produces antenna speed without travel, so rotating machines never use it
    const speedSaysMoving =
      !profile.rotatingUpper &&
      typeof f.speedKmh === 'number' &&
      typeof last.speedKmh === 'number' &&
      (p.moveRule === 'both'
        ? f.speedKmh >= p.minMoveKmh && last.speedKmh >= p.minMoveKmh
        : f.speedKmh >= p.minMoveKmh || last.speedKmh >= p.minMoveKmh);
    const k = speedSaysMoving ? (dt >= p.sparseDtS ? p.kSigmaMovingSparse : p.kSigmaMoving) : p.kSigma;
    const radius = Math.max(p.baseRadiusM, k * Math.sqrt(anchorSigma ** 2 + sf ** 2));
    if (dA > radius) {
      res.km += dA / 1000;
      anchor = f;
      anchorSigma = sf;
    }
    last = f;
  }
  return res;
}

/** Naive sum of consecutive distances — kept only to quantify how wrong it is. */
export function naiveDistanceKm(fixes: Fix[]): number {
  const s = fixes.filter((f) => validLatLon(f.lat, f.lon)).sort((a, b) => a.t - b.t);
  let m = 0;
  for (let i = 1; i < s.length; i++) m += haversineM(s[i - 1].lat, s[i - 1].lon, s[i].lat, s[i].lon);
  return m / 1000;
}
