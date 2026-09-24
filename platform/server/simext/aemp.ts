// Эмуляция AEMP 2.0 (ISO 15143-3): снимок парка /Fleet/{page} с Basic-авторизацией, JSON и XML.
import { getDb } from '../db.js';
import { verifyPassword } from '../auth.js';
import { simextCompany, type SimextCompany, type SimextUnit } from './model.js';
import {
  accountByLogin,
  ensureSimextSchema,
  latestSimextMessages,
  messageIso,
  messageParams,
  type SimextAccount,
  type SimextMessageRow,
} from './store.js';

const PAGE_SIZE = 100;

const esc = (v: unknown): string =>
  String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const leaf = (name: string, v: unknown): string => `<${name}>${esc(v)}</${name}>`;

const dtAttr = (dt: string | undefined): string => (dt ? ` datetime="${esc(dt)}"` : '');

const unauthorized = (): Response =>
  new Response('Требуется базовая авторизация (логин и пароль компании).\n', {
    status: 401,
    headers: { 'www-authenticate': 'Basic realm="AEMP"', 'content-type': 'text/plain; charset=utf-8' },
  });

const infoPage = (prefix: string): Response =>
  new Response(
    `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>AEMP 2.0 — эмуляция (стенд ITles)</title></head>` +
      `<body><h1>AEMP 2.0 (ISO 15143-3) — эмуляция (стенд ITles)</h1>` +
      `<p>Это не настоящий портал производителя: машины моделируются стендом ITles, а снимок парка отдаётся ` +
      `по стандарту ISO 15143-3 с базовой авторизацией.</p><p>Адрес снимка: <code>${esc(prefix)}/Fleet/1</code>.</p></body></html>`,
    { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } },
  );

async function basicAuth(req: Request): Promise<SimextAccount | null> {
  const h = req.headers.get('authorization') ?? '';
  if (!h.startsWith('Basic ')) return null;
  let decoded: string;
  try {
    decoded = Buffer.from(h.slice(6).trim(), 'base64').toString('utf8');
  } catch {
    return null;
  }
  const sep = decoded.indexOf(':');
  if (sep < 0) return null;
  const db = await getDb();
  await ensureSimextSchema(db);
  const acc = await accountByLogin(db, 'aemp', decoded.slice(0, sep));
  if (!acc || !(await verifyPassword(decoded.slice(sep + 1), acc.pass_hash))) return null;
  return acc;
}

export async function handleAemp(req: Request, prefix = ''): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname.slice(prefix.length) || '/';
  if (path === '/' || path === '/Fleet') return infoPage(prefix);
  const m = /^\/Fleet\/(\d+)$/.exec(path);
  if (!m) return new Response('Не найдено\n', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  const acc = await basicAuth(req);
  if (!acc) return unauthorized();
  const company = simextCompany(acc.company_id);
  if (!company) return unauthorized();
  const page = Math.max(1, Number(m[1]));
  const db = await getDb();
  const last = await latestSimextMessages(db, company.id);
  const total = company.units.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const slice = [...company.units].sort((a, b) => a.uid.localeCompare(b.uid)).slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const base = `${url.origin}${prefix}/Fleet`;
  const links: Array<{ rel: string; href: string }> = [{ rel: 'self', href: `${base}/${page}` }];
  if (page < pages) links.push({ rel: 'next', href: `${base}/${page + 1}` });
  links.push({ rel: 'last', href: `${base}/${pages}` });
  const equipment = slice.map((u) => equipmentOf(u, last.get(u.uid), company));
  const accept = (req.headers.get('accept') ?? '').toLowerCase();
  if (accept.includes('xml') && !accept.includes('json')) {
    return new Response(toXml(equipment, links), {
      status: 200,
      headers: { 'content-type': 'application/xml; charset=utf-8', 'cache-control': 'no-store' },
    });
  }
  return new Response(JSON.stringify({ Fleet: { Equipment: equipment, links } }), {
    status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

interface EquipmentDoc {
  EquipmentHeader: Record<string, unknown>;
  Location?: { datetime: string; Latitude: number; Longitude: number; Altitude?: number };
  CumulativeOperatingHours?: { datetime: string; Hour: number };
  Distance?: { datetime: string; Odometer: number; OdometerUnits: string };
  FuelUsed?: { datetime: string; FuelConsumed: number; FuelUnits: string };
  FuelRemaining?: { datetime: string; Percent: number };
  EngineStatus?: { datetime: string; Running: boolean };
}

function equipmentOf(u: SimextUnit, row: SimextMessageRow | undefined, company: SimextCompany): EquipmentDoc {
  const p = row ? messageParams(row) : {};
  const dt = row ? messageIso(row.t) : undefined;
  const out: EquipmentDoc = {
    EquipmentHeader: { OEMName: company.oem ?? null, Model: u.vehicle_model ?? null, EquipmentID: u.name, SerialNumber: u.uid, PIN: u.uid },
  };
  if (row && typeof p.engine_hours === 'number') out.CumulativeOperatingHours = { datetime: dt!, Hour: p.engine_hours };
  if (row && typeof p.odometer_km === 'number') out.Distance = { datetime: dt!, Odometer: p.odometer_km, OdometerUnits: 'kilometre' };
  if (row && typeof p.fuel_used_l === 'number') out.FuelUsed = { datetime: dt!, FuelConsumed: p.fuel_used_l, FuelUnits: 'litre' };
  if (row && typeof p.fuel_level_pct === 'number') out.FuelRemaining = { datetime: dt!, Percent: p.fuel_level_pct };
  if (row && typeof p.ignition === 'number') out.EngineStatus = { datetime: dt!, Running: p.ignition === 1 };
  if (row && row.lat !== null && row.lon !== null) {
    out.Location = {
      datetime: dt!,
      Latitude: row.lat,
      Longitude: row.lon,
      ...(row.alt !== null ? { Altitude: row.alt } : {}),
    };
  }
  return out;
}

function toXml(equipment: EquipmentDoc[], links: Array<{ rel: string; href: string }>): string {
  const body = equipment
    .map((e) => {
      const h = e.EquipmentHeader;
      const parts: string[] = [
        `<EquipmentHeader>` +
          leaf('OEMName', h.OEMName ?? '') +
            leaf('Model', h.Model ?? '') +
            leaf('EquipmentID', h.EquipmentID ?? '') +
            leaf('SerialNumber', h.SerialNumber ?? '') +
            leaf('PIN', h.PIN ?? '') +
          `</EquipmentHeader>`,
      ];
      const loc = e.Location;
      if (loc)
        parts.push(
          `<Location${dtAttr(loc.datetime)}>${leaf('Latitude', loc.Latitude)}${leaf('Longitude', loc.Longitude)}${
            loc.Altitude === undefined ? '' : leaf('Altitude', loc.Altitude)
          }</Location>`,
        );
      const coh = e.CumulativeOperatingHours;
      if (coh) parts.push(`<CumulativeOperatingHours${dtAttr(coh.datetime)}>${leaf('Hour', coh.Hour)}</CumulativeOperatingHours>`);
      const dist = e.Distance;
      if (dist)
        parts.push(`<Distance${dtAttr(dist.datetime)}>${leaf('Odometer', dist.Odometer)}${leaf('OdometerUnits', dist.OdometerUnits)}</Distance>`);
      const fu = e.FuelUsed;
      if (fu) parts.push(`<FuelUsed${dtAttr(fu.datetime)}>${leaf('FuelConsumed', fu.FuelConsumed)}${leaf('FuelUnits', fu.FuelUnits)}</FuelUsed>`);
      const fr = e.FuelRemaining;
      if (fr) parts.push(`<FuelRemaining${dtAttr(fr.datetime)}>${leaf('Percent', fr.Percent)}</FuelRemaining>`);
      const es = e.EngineStatus;
      if (es) parts.push(`<EngineStatus${dtAttr(es.datetime)}>${leaf('Running', es.Running)}</EngineStatus>`);
      return `<Equipment>${parts.join('')}</Equipment>`;
    })
    .join('');
  const linkXml = links.map((l) => `<link rel="${esc(l.rel)}" href="${esc(l.href)}"/>`).join('');
  return `<?xml version="1.0" encoding="utf-8"?><Fleet>${body}<links>${linkXml}</links></Fleet>`;
}
