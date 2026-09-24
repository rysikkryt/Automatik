import type { IngestRecord } from '../ingest.js';
import { SENSORS } from '../domain/sensors.js';
import { ConnectorError, fetchJson, trimBase, type RemoteUnit } from './types.js';

/**
 * Wialon Remote API (help.wialon.com/en/api). Works with Wialon Hosting (hst-api.wialon.com)
 * and with Wialon Local servers of Russian integrators (Wialon Hosting answers HTTP 403 to
 * Russian IP addresses — measured from 10 Russian networks on 2026-09-23 — so Russian fleets
 * run on Wialon Local). Formats used here are from the official data-format pages:
 *   pos: { t, y: latitude, x: longitude, z, s: speed, c: course, sc: satellites }
 *   counters (flag 0x2000): cnm mileage (km or miles by unit measure system), cneh engine hours (h)
 */
export interface WialonConfig {
  baseUrl: string; // API origin, e.g. https://hst-api.wialon.com or https://wialon.integrator.ru
  token: string;
}

const FLAG_BASE = 0x1;
const FLAG_LAST_POS = 0x400;
const FLAG_COUNTERS = 0x2000;

const WIALON_ERRORS: Record<number, string> = {
  1: 'недействительная сессия',
  4: 'неверные параметры запроса',
  5: 'ошибка выполнения запроса',
  6: 'неизвестная ошибка',
  7: 'доступ запрещён',
  8: 'неверный токен или пользователь',
  1003: 'нужно сжатие ответа',
};

export async function wialonCall(base: string, svc: string, params: unknown, sid?: string): Promise<any> {
  const body = new URLSearchParams({ params: JSON.stringify(params) });
  if (sid) body.set('sid', sid);
  const r = await fetchJson(`${base}/wialon/ajax.html?svc=${encodeURIComponent(svc)}`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body,
    timeoutMs: 60_000,
  });
  if (r && typeof r === 'object' && !Array.isArray(r) && typeof r.error === 'number' && r.error !== 0) {
    const code = r.error === 8 || r.error === 1 ? 'auth' : 'api';
    throw new ConnectorError(code, `Wialon: ${WIALON_ERRORS[r.error] ?? 'ошибка ' + r.error}${r.reason ? ' (' + r.reason + ')' : ''}`);
  }
  return r;
}

/** Message parameters carry sensor values; keys follow the ITles sensor registry so they pass ingestion. */
function paramsToSensors(prm: Record<string, unknown>): Record<string, number> {
  const sensors: Record<string, number> = {};
  for (const [k, v] of Object.entries(prm)) {
    if (SENSORS[k] && typeof v === 'number' && Number.isFinite(v)) sensors[k] = v;
  }
  return sensors;
}

// Message speed is stored in km/h regardless of the unit's display measure system.
export function wialonMessageToRecord(m: any, _mileageFactor = 1): IngestRecord | null {
  if (!m || typeof m.t !== 'number') return null;
  const rec: IngestRecord = { t: m.t };
  const p = m.pos;
  if (p && typeof p.y === 'number' && typeof p.x === 'number') {
    rec.lat = p.y;
    rec.lon = p.x;
    if (typeof p.s === 'number') rec.speed_kmh = p.s;
    if (typeof p.c === 'number') rec.course = p.c;
    if (typeof p.z === 'number') rec.alt = p.z;
    if (typeof p.sc === 'number') rec.sats = p.sc;
  }
  const prm = m.p ?? {};
  if (typeof prm.hdop === 'number') rec.hdop = prm.hdop;
  const sensors = paramsToSensors(prm);
  if (Object.keys(sensors).length) rec.sensors = sensors;
  // Wialon Local feeds also expose the counters as message parameters: history sync keeps
  // the same method attribution as the item-level counters.
  if (typeof prm.engine_hours === 'number' && Number.isFinite(prm.engine_hours) && prm.engine_hours >= 0) {
    rec.engine_hours = prm.engine_hours;
    rec.engine_hours_method = 'platform';
  }
  if (typeof prm.odometer_km === 'number' && Number.isFinite(prm.odometer_km) && prm.odometer_km >= 0) {
    rec.odometer_km = prm.odometer_km;
    rec.odometer_method = 'platform';
  }
  return rec;
}

export function wialonUnitToRecords(u: any): IngestRecord[] {
  // measure system: 0 metric, 1 U.S., 2 imperial, 3 metric with gallons
  const factor = u.mu === 1 || u.mu === 2 ? 1.609344 : 1;
  const out: IngestRecord[] = [];
  if (u.pos) {
    const r = wialonMessageToRecord({ t: u.pos.t, pos: u.pos, p: u.lmsg?.p }, factor);
    if (r) out.push(r);
  }
  const tc = u.lmsg?.t ?? u.pos?.t;
  if (typeof tc === 'number') {
    const rec: IngestRecord = { t: tc };
    if (typeof u.cneh === 'number' && u.cneh > 0) {
      rec.engine_hours = u.cneh;
      rec.engine_hours_method = 'platform';
    }
    if (typeof u.cnm === 'number' && u.cnm > 0) {
      rec.odometer_km = u.cnm * factor;
      rec.odometer_method = 'platform';
    }
    const sensors = paramsToSensors(u.lmsg?.p ?? {});
    if (Object.keys(sensors).length) rec.sensors = sensors;
    if (rec.engine_hours !== undefined || rec.odometer_km !== undefined) out.push(rec);
  }
  return out;
}

export async function wialonUnits(cfg: WialonConfig, historyFrom?: Date): Promise<RemoteUnit[]> {
  const base = trimBase(cfg.baseUrl);
  const login = await wialonCall(base, 'token/login', { token: cfg.token, fl: 1 });
  const sid: string = login.eid;
  if (!sid) throw new ConnectorError('auth', 'Wialon не вернул идентификатор сессии');
  const res = await wialonCall(
    base,
    'core/search_items',
    {
      spec: { itemsType: 'avl_unit', propName: 'sys_name', propValueMask: '*', sortType: 'sys_name' },
      force: 1,
      flags: FLAG_BASE | FLAG_LAST_POS | FLAG_COUNTERS,
      from: 0,
      to: 0,
    },
    sid,
  );
  const units: RemoteUnit[] = [];
  for (const u of res.items ?? []) {
    const records = wialonUnitToRecords(u);
    if (historyFrom) {
      const factor = u.mu === 1 || u.mu === 2 ? 1.609344 : 1;
      const hist = await wialonCall(
        base,
        'messages/load_interval',
        {
          itemId: u.id,
          timeFrom: Math.floor(historyFrom.getTime() / 1000),
          timeTo: Math.floor(Date.now() / 1000),
          flags: 0x1,
          flagsMask: 0xff01,
          loadCount: 0xffffffff,
        },
        sid,
      );
      for (const m of hist.messages ?? []) {
        const r = wialonMessageToRecord(m, factor);
        if (r) records.push(r);
      }
      await wialonCall(base, 'messages/unload', {}, sid).catch(() => {});
    }
    units.push({ id: String(u.id), name: u.nm ?? `Wialon ${u.id}`, records });
  }
  await wialonCall(base, 'core/logout', {}, sid).catch(() => {});
  return units;
}

/** URL of the official Wialon authorization page that returns a read-only token (2 clicks). */
export function wialonLoginUrl(loginHost: string, redirectUri: string): string {
  const q = new URLSearchParams({
    client_id: 'ITles',
    access_type: '0x100', // "online tracking": read-only access to units, messages and reports
    activation_time: '0',
    duration: '0',
    lang: 'ru',
    flags: '0x1',
    redirect_uri: redirectUri,
    response_type: 'token',
  });
  return `${trimBase(loginHost)}/login.html?${q}`;
}
