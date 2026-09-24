import type { IngestRecord } from '../ingest.js';
import { ConnectorError, fetchJson, trimBase, type RemoteUnit } from './types.js';

/**
 * Traccar REST API (open-source server used by many integrators).
 * Units verified in Traccar source: speed in knots, attributes.hours in milliseconds
 * (EngineHoursHandler), attributes.odometer / totalDistance in metres.
 */
export interface TraccarConfig {
  baseUrl: string;
  token?: string;
  email?: string;
  password?: string;
}

function headers(cfg: TraccarConfig): Record<string, string> {
  if (cfg.token) return { authorization: `Bearer ${cfg.token}`, accept: 'application/json' };
  if (cfg.email && cfg.password)
    return { authorization: 'Basic ' + Buffer.from(`${cfg.email}:${cfg.password}`).toString('base64'), accept: 'application/json' };
  throw new ConnectorError('config', 'Укажите токен Traccar или логин и пароль');
}

export function traccarPositionToRecord(p: any): IngestRecord | null {
  const a = p.attributes ?? {};
  const t = p.fixTime ?? p.deviceTime;
  if (!t) return null;
  const rec: IngestRecord = { t };
  if (p.valid !== false && typeof p.latitude === 'number' && typeof p.longitude === 'number') {
    rec.lat = p.latitude;
    rec.lon = p.longitude;
    if (typeof p.speed === 'number') rec.speed_kmh = p.speed * 1.852;
    if (typeof p.course === 'number') rec.course = p.course;
    if (typeof p.altitude === 'number') rec.alt = p.altitude;
    if (typeof a.sat === 'number') rec.sats = a.sat;
    if (typeof a.hdop === 'number') rec.hdop = a.hdop;
    if (typeof p.accuracy === 'number' && p.accuracy > 0) rec.acc_m = p.accuracy;
  }
  if (typeof a.hours === 'number' && a.hours > 0) {
    rec.engine_hours = a.hours / 3600e3;
    rec.engine_hours_method = 'platform';
  }
  // device odometer only; Traccar's own totalDistance is naive GNSS summing, our odometry is better
  if (typeof a.odometer === 'number' && a.odometer > 0) {
    rec.odometer_km = a.odometer / 1000;
    rec.odometer_method = 'platform';
  }
  return rec;
}

export async function traccarUnits(cfg: TraccarConfig, historyFrom?: Date): Promise<RemoteUnit[]> {
  const base = trimBase(cfg.baseUrl);
  const h = headers(cfg);
  const devices = await fetchJson(`${base}/api/devices`, { headers: h });
  if (!Array.isArray(devices)) throw new ConnectorError('format', 'Ответ Traccar /api/devices не является списком');
  const latest = await fetchJson(`${base}/api/positions`, { headers: h });
  const units: RemoteUnit[] = [];
  for (const d of devices) {
    const records: IngestRecord[] = [];
    if (historyFrom) {
      const q = new URLSearchParams({ deviceId: String(d.id), from: historyFrom.toISOString(), to: new Date().toISOString() });
      const hist = await fetchJson(`${base}/api/positions?${q}`, { headers: h, timeoutMs: 60_000 });
      if (Array.isArray(hist)) for (const p of hist) {
        const r = traccarPositionToRecord(p);
        if (r) records.push(r);
      }
    }
    for (const p of Array.isArray(latest) ? latest : []) {
      if (p.deviceId !== d.id) continue;
      const r = traccarPositionToRecord(p);
      if (r) records.push(r);
    }
    units.push({ id: String(d.id), name: d.name ?? d.uniqueId ?? `Traccar ${d.id}`, model: d.model ?? null, records });
  }
  return units;
}
