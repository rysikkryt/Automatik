import type { IngestRecord } from '../ingest.js';
import { ConnectorError, fetchJson, trimBase, type RemoteUnit } from './types.js';

/**
 * ISO 15143-3:2016 (AEMP 2.0) fleet snapshot, JSON or XML: Equipment[] with EquipmentHeader,
 * Location, CumulativeOperatingHours and Distance — exactly the three values of the TZ. One
 * connector covers every OEM that publishes the standard API.
 */
export interface AempConfig {
  baseUrl: string; // endpoint that returns the Fleet snapshot, page 1 (e.g. https://oem.example/Fleet/1)
  token?: string;
  username?: string;
  password?: string;
}

const lower = (o: any): any => {
  if (Array.isArray(o)) return o.map(lower);
  if (o && typeof o === 'object') {
    const r: any = {};
    for (const [k, v] of Object.entries(o)) r[k.toLowerCase()] = lower(v);
    return r;
  }
  return o;
};

const toNum = (v: any): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(String(v).replace(',', '.'));
  return Number.isFinite(n) ? n : null;
};

function distanceKm(value: number, units: string | undefined): number {
  const u = (units ?? 'kilometre').toLowerCase();
  if (u.startsWith('mi')) return value * 1.609344;
  if (u === 'metre' || u === 'meter' || u === 'm') return value / 1000;
  return value;
}

/** Minimal XML → object conversion sufficient for AEMP documents (elements, attributes, text). */
export function parseXml(xml: string): any {
  const stack: any[] = [{ children: {} }];
  const re = /<(\/?)([A-Za-z_][\w:.-]*)([^>]*?)(\/?)>|([^<]+)/g;
  let m: RegExpExecArray | null;
  const clean = xml.replace(/<\?[\s\S]*?\?>/g, '').replace(/<!--[\s\S]*?-->/g, '');
  while ((m = re.exec(clean))) {
    const [, closing, rawName, attrs, selfClose, text] = m;
    if (text !== undefined) {
      const t = text.trim();
      if (t) stack[stack.length - 1].text = (stack[stack.length - 1].text ?? '') + t;
      continue;
    }
    const name = rawName.includes(':') ? rawName.split(':').pop()! : rawName;
    if (closing) {
      const node = stack.pop();
      const parent = stack[stack.length - 1];
      const value = Object.keys(node.children).length || Object.keys(node.attrs).length ? { ...node.attrs, ...node.children, ...(node.text ? { _text: node.text } : {}) } : node.text ?? '';
      const prev = parent.children[name];
      parent.children[name] = prev === undefined ? value : Array.isArray(prev) ? [...prev, value] : [prev, value];
      continue;
    }
    const a: any = {};
    attrs.replace(/([\w:.-]+)\s*=\s*"([^"]*)"/g, (_s, k, v) => ((a[k.includes(':') ? k.split(':').pop() : k] = v), ''));
    if (selfClose) {
      const parent = stack[stack.length - 1];
      const prev = parent.children[name];
      parent.children[name] = prev === undefined ? a : Array.isArray(prev) ? [...prev, a] : [prev, a];
    } else stack.push({ name, attrs: a, children: {} });
  }
  return stack[0].children;
}

const txt = (v: any) => (v && typeof v === 'object' && '_text' in v ? v._text : v);

export function parseAempFleet(doc: any): { units: RemoteUnit[]; next: string | null } {
  const d = lower(typeof doc === 'string' ? parseXml(doc) : doc);
  const fleet = d.fleet ?? d;
  let eq = fleet.equipment ?? [];
  if (!Array.isArray(eq)) eq = [eq];
  const units: RemoteUnit[] = [];
  for (const e of eq) {
    const h = e.equipmentheader ?? {};
    const id = txt(h.serialnumber) ?? txt(h.equipmentid) ?? txt(h.pin);
    if (!id) continue;
    const records: IngestRecord[] = [];
    const loc = e.location;
    if (loc) {
      const lat = toNum(txt(loc.latitude));
      const lon = toNum(txt(loc.longitude));
      const t = loc.datetime;
      if (lat !== null && lon !== null && t) {
        const r: IngestRecord = { t, lat, lon };
        const alt = toNum(txt(loc.altitude));
        if (alt !== null) r.alt = alt;
        records.push(r);
      }
    }
    const coh = e.cumulativeoperatinghours;
    const hour = coh ? toNum(txt(coh.hour)) : null;
    if (coh && hour !== null && coh.datetime) records.push({ t: coh.datetime, engine_hours: hour, engine_hours_method: 'ecu' });
    const dist = e.distance;
    const odo = dist ? toNum(txt(dist.odometer)) : null;
    if (dist && odo !== null && dist.datetime)
      records.push({ t: dist.datetime, odometer_km: distanceKm(odo, txt(dist.odometerunits)), odometer_method: 'ecu' });
    const fu = e.fuelused;
    const consumed = fu ? toNum(txt(fu.fuelconsumed)) : null;
    const fuelUnits = fu ? String(txt(fu.fuelunits) ?? 'litre').toLowerCase() : '';
    if (fu && consumed !== null && fu.datetime && (fuelUnits === 'litre' || fuelUnits === 'l'))
      records.push({ t: fu.datetime, sensors: { fuel_used_l: consumed } });
    const fr = e.fuelremaining;
    const pct = fr ? toNum(txt(fr.percent)) : null;
    if (fr && pct !== null && fr.datetime) records.push({ t: fr.datetime, sensors: { fuel_level_pct: pct } });
    units.push({ id: String(id), name: [txt(h.oemname), txt(h.model), id].filter(Boolean).join(' '), make: txt(h.oemname) ?? null, model: txt(h.model) ?? null, records });
  }
  let links = fleet.links ?? fleet.link ?? [];
  if (!Array.isArray(links)) links = [links];
  const next = links.find((l: any) => String(txt(l.rel) ?? '').toLowerCase() === 'next');
  return { units, next: next ? String(txt(next.href)) : null };
}

export async function aempUnits(cfg: AempConfig): Promise<RemoteUnit[]> {
  let url: string | null = trimBase(cfg.baseUrl);
  const headers: Record<string, string> = { accept: 'application/json, application/xml;q=0.9' };
  if (cfg.token) headers.authorization = `Bearer ${cfg.token}`;
  else if (cfg.username && cfg.password)
    headers.authorization = 'Basic ' + Buffer.from(`${cfg.username}:${cfg.password}`).toString('base64');
  const all: RemoteUnit[] = [];
  for (let page = 0; url && page < 100; page++) {
    const body = await fetchJson(url, { headers, timeoutMs: 60_000 });
    const { units, next } = parseAempFleet(body);
    all.push(...units);
    if (!next || next === url) break;
    url = new URL(next, url).toString();
  }
  if (all.length === 0) throw new ConnectorError('format', 'Ответ не содержит ни одной единицы техники в формате ISO 15143-3');
  return all;
}
