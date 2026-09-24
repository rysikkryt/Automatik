import { SCHEMA_SQL, SCHEMA_VERSION } from './schema.js';

export interface QueryResult<T> {
  rows: T[];
  rowCount: number;
}

export interface Db {
  kind: 'pg' | 'pglite';
  query<T = Record<string, any>>(sql: string, params?: unknown[]): Promise<QueryResult<T>>;
  exec(sql: string): Promise<void>;
  tx<T>(fn: (q: Db) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export class DbNotConfigured extends Error {
  constructor() {
    super('DATABASE_URL is not set');
  }
}

let cached: Promise<Db> | null = null;

export function getDb(url = process.env.DATABASE_URL): Promise<Db> {
  if (!url) return Promise.reject(new DbNotConfigured());
  if (!cached) {
    cached = openDb(url)
      .then(async (db) => {
        await migrate(db);
        return db;
      })
      .catch((e) => {
        cached = null;
        throw e;
      });
  }
  return cached;
}

export async function openDb(url: string): Promise<Db> {
  if (url.startsWith('pglite:')) return openPglite(url.slice('pglite:'.length));
  return openPg(url);
}

async function openPglite(path: string): Promise<Db> {
  const { PGlite } = await import('@electric-sql/pglite');
  const persistent = !!path && path !== 'memory';
  if (persistent) (await import('node:fs')).mkdirSync(path, { recursive: true });
  const pg = persistent ? new PGlite(path) : new PGlite();
  await pg.waitReady;
  const wrap = (q: any): Db => ({
    kind: 'pglite',
    async query(sql, params) {
      const r = await q.query(sql, params ?? []);
      return { rows: r.rows, rowCount: r.affectedRows ?? r.rows.length };
    },
    async exec(sql) {
      await q.exec(sql);
    },
    async tx(fn) {
      if (q !== pg) return fn(wrap(q));
      return pg.transaction(async (t: any) => fn(wrap(t)));
    },
    async close() {
      if (q === pg) await pg.close();
    },
  });
  return wrap(pg);
}

async function openPg(url: string): Promise<Db> {
  const mod: any = await import('pg');
  const Pool = (mod.default ?? mod).Pool;
  // serverless: few connections per instance; Neon/PgBouncer pooled URLs are recommended
  const pool = new Pool({ connectionString: url, max: 3, idleTimeoutMillis: 10_000 });
  const wrap = (client: any, isPool: boolean): Db => ({
    kind: 'pg',
    async query(sql, params) {
      const r = await client.query(sql, params ?? []);
      return { rows: r.rows, rowCount: r.rowCount ?? r.rows.length };
    },
    async exec(sql) {
      await client.query(sql);
    },
    async tx(fn) {
      if (!isPool) return fn(wrap(client, false));
      const c = await pool.connect();
      try {
        await c.query('begin');
        const out = await fn(wrap(c, false));
        await c.query('commit');
        return out;
      } catch (e) {
        await c.query('rollback').catch(() => {});
        throw e;
      } finally {
        c.release();
      }
    },
    async close() {
      if (isPool) await pool.end();
    },
  });
  return wrap(pool, true);
}

export async function migrate(db: Db): Promise<void> {
  try {
    const r = await db.query<{ value: string }>(`select value from schema_meta where key = 'version'`);
    if (r.rows[0]?.value === SCHEMA_VERSION) return;
  } catch {
    // fresh database
  }
  await db.exec(SCHEMA_SQL);
  await db.query(
    `insert into schema_meta (key, value) values ('version', $1) on conflict (key) do update set value = excluded.value`,
    [SCHEMA_VERSION],
  );
}
