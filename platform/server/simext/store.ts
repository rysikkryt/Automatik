import type { Db } from '../db.js';

const ensured = new WeakMap<Db, Promise<void>>();

/** The emulated platforms own their tables; created lazily so the main schema stays untouched. */
export async function ensureSimextSchema(db: Db): Promise<void> {
  let p = ensured.get(db);
  if (!p) {
    p = (async () => {
      await db.exec(`create table if not exists simext_accounts (
        company_id text primary key,
        platform text not null,
        login text not null,
        pass_hash text not null,
        token_hash text,
        token_enc text,
        updated_at timestamptz default now()
      )`);
      await db.exec(`create table if not exists simext_messages (
        company_id text,
        unit_uid text,
        t timestamptz,
        lat double precision,
        lon double precision,
        speed_kmh real,
        course real,
        alt real,
        sats int,
        params jsonb,
        primary key (company_id, unit_uid, t)
      )`);
    })();
    ensured.set(db, p);
  }
  return p;
}

export interface SimextAccount {
  company_id: string;
  platform: string;
  login: string;
  pass_hash: string;
  token_hash: string | null;
  token_enc: string | null;
}

export interface SimextMessageRow {
  unit_uid: string;
  t: Date | string;
  lat: number | null;
  lon: number | null;
  speed_kmh: number | null;
  course: number | null;
  alt: number | null;
  sats: number | null;
  params: Record<string, unknown> | null;
}

export interface SimextPushRow {
  unit: string;
  t: string;
  lat: number | null;
  lon: number | null;
  speed: number | null;
  course: number | null;
  alt: number | null;
  sats: number | null;
  params: Record<string, unknown>;
}

export async function accountByTokenHash(db: Db, tokenHash: string): Promise<SimextAccount | null> {
  if (!tokenHash) return null;
  const r = await db.query<SimextAccount>(
    `select company_id, platform, login, pass_hash, token_hash, token_enc from simext_accounts where token_hash = $1`,
    [tokenHash],
  );
  return r.rows[0] ?? null;
}

export async function accountByLogin(db: Db, platform: string, login: string): Promise<SimextAccount | null> {
  if (!login) return null;
  const r = await db.query<SimextAccount>(
    `select company_id, platform, login, pass_hash, token_hash, token_enc from simext_accounts where platform = $1 and login = $2`,
    [platform, login],
  );
  return r.rows[0] ?? null;
}

export async function insertSimextMessages(db: Db, companyId: string, rows: SimextPushRow[]): Promise<number> {
  let stored = 0;
  for (let i = 0; i < rows.length; i += 400) {
    const chunk = rows.slice(i, i + 400);
    const params: unknown[] = [];
    const values = chunk
      .map((r) => {
        const ph = [companyId, r.unit, r.t, r.lat, r.lon, r.speed, r.course, r.alt, r.sats, JSON.stringify(r.params)].map((v) => {
          params.push(v);
          return `$${params.length}`;
        });
        return `(${ph[0]}, ${ph[1]}, ${ph[2]}::timestamptz, ${ph[3]}, ${ph[4]}, ${ph[5]}, ${ph[6]}, ${ph[7]}, ${ph[8]}, ${ph[9]}::jsonb)`;
      })
      .join(',');
    const r = await db.query(
      `insert into simext_messages (company_id, unit_uid, t, lat, lon, speed_kmh, course, alt, sats, params)
       values ${values} on conflict (company_id, unit_uid, t) do nothing`,
      params,
    );
    stored += r.rowCount;
  }
  return stored;
}

export async function latestSimextMessages(db: Db, companyId: string): Promise<Map<string, SimextMessageRow>> {
  const r = await db.query<SimextMessageRow>(
    `select distinct on (unit_uid) unit_uid, t, lat, lon, speed_kmh, course, alt, sats, params
       from simext_messages where company_id = $1 order by unit_uid, t desc`,
    [companyId],
  );
  return new Map(r.rows.map((row) => [row.unit_uid, row]));
}

export async function simextHistory(db: Db, companyId: string, uid: string, fromSec: number, toSec: number): Promise<SimextMessageRow[]> {
  const r = await db.query<SimextMessageRow>(
    `select unit_uid, t, lat, lon, speed_kmh, course, alt, sats, params from simext_messages
      where company_id = $1 and unit_uid = $2 and t >= to_timestamp($3) and t <= to_timestamp($4) order by t`,
    [companyId, uid, fromSec, toSec],
  );
  return r.rows;
}

export const messageSeconds = (t: Date | string): number =>
  Math.floor((t instanceof Date ? t.getTime() : Date.parse(String(t))) / 1000);

export const messageIso = (t: Date | string): string => (t instanceof Date ? t.toISOString() : new Date(t).toISOString());

export const messageParams = (row: SimextMessageRow): Record<string, unknown> =>
  row.params && typeof row.params === 'object' ? row.params : {};
