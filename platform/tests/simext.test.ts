import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { call } from './helpers.js';
import { getDb } from '../server/db.js';
import { upsertSimextCredentials, type SimextCredential } from '../server/simext/credentials.js';
import { handleWithSimext } from '../server/simext/index.js';
import { fetchUnits } from '../server/connectors/sync.js';
import { parseAempFleet } from '../server/connectors/aemp.js';
import raw from '../server/simext/companies.json';

process.env.DATABASE_URL = process.env.TEST_DATABASE_URL ?? 'pglite:memory';
process.env.SETUP_KEY = 'test-setup-key-0123456789';
process.env.GATEWAY_TOKEN = 'gw_test_token_0123456789abcdef';

const GW = process.env.GATEWAY_TOKEN;
const WIALON = 'https://severles-wialon.vercel.app';
const AEMP = 'https://granit-aemp.vercel.app/Fleet/1';
const C = raw as any;

const wialonCompany = C.companies.find((c: any) => c.platform === 'wialon');
const aempCompany = C.companies.find((c: any) => c.platform === 'aemp');

const simRequest = (url: string, init?: RequestInit): Promise<Response> => handleWithSimext(new Request(url, init));

const realFetch = globalThis.fetch;
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => simRequest(String(input), init)) as typeof fetch;
afterAll(() => {
  globalThis.fetch = realFetch;
});

let creds: SimextCredential[] = [];
const pushed = new Map<string, any[]>();

const ajax = (svc: string, params: unknown, sid?: string) =>
  simRequest(`${WIALON}/wialon/ajax.html?svc=${encodeURIComponent(svc)}`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ params: JSON.stringify(params), ...(sid ? { sid } : {}) }).toString(),
  });

describe('simext: эмуляции Wialon и AEMP 2.0', () => {
  beforeAll(async () => {
    creds = await upsertSimextCredentials(await getDb());
    const now = Math.floor(Date.now() / 1000);
    for (const c of [wialonCompany, aempCompany]) {
      const records: any[] = [];
      c.units.forEach((u: any, ui: number) => {
        for (let i = 0; i < 13; i++) {
          const moving = i % 3 !== 0;
          records.push({
            unit: u.uid,
            t: now - 6 * 3600 + i * 1800,
            lat: 61.5 + ui * 0.01 + i * 0.0004,
            lon: 34.2 + ui * 0.02 + i * 0.0006,
            speed: moving ? 12 + ui * 3 + i : 0,
            course: (i * 27 + ui * 40) % 360,
            alt: 80 + ui,
            sats: 9 + (i % 4),
            params: {
              engine_hours: 1200 + ui * 100 + i * 0.5,
              odometer_km: 5400 + ui * 300 + i * 0.9,
              fuel_level_l: Math.max(10, u.tank_l - i * 2 - ui * 3),
              fuel_level_pct: Math.max(3, 95 - i * 2),
              fuel_used_l: 4000 + ui * 200 + i * 1.4,
              rpm: moving ? 1450 + ui * 60 : 0,
              coolant_c: 78 + (i % 5),
              engine_load_pct: moving ? 62 : 5,
              ignition: moving ? 1 : 0,
              pwr_v: 27.4 - (i % 3) * 0.4,
            },
          });
        }
      });
      pushed.set(c.id, records);
      const r = await call('POST', '/api/simext/push', { company: c.id, records }, GW);
      expect(r.status).toBe(200);
      expect(r.data.stored).toBe(records.length);
      expect(r.data.duplicates).toBe(0);
    }
  });

  it('приём данных стенда требует ключ шлюза', async () => {
    const r = await call('POST', '/api/simext/push', { company: wialonCompany.id, records: [] });
    expect(r.status).toBe(401);
  });

  it('повторная выгрузка считается дубликатами, неизвестные машины отмечаются', async () => {
    const again = await call('POST', '/api/simext/push', { company: wialonCompany.id, records: pushed.get(wialonCompany.id) }, GW);
    expect(again.data.stored).toBe(0);
    expect(again.data.duplicates).toBe(pushed.get(wialonCompany.id)!.length);
    const unknown = await call(
      'POST',
      '/api/simext/push',
      { company: wialonCompany.id, records: [{ unit: '999999999999999', t: Math.floor(Date.now() / 1000), lat: 1, lon: 2 }] },
      GW,
    );
    expect(unknown.data.stored).toBe(0);
    expect(unknown.data.unknown_units).toEqual(['999999999999999']);
  });

  it('коннектор Wialon получает машины, позиции, моточасы, пробег и топливо', async () => {
    const cred = creds.find((c) => c.platform === 'wialon')!;
    const units = await fetchUnits('wialon', WIALON, { token: cred.token! }, new Date(Date.now() - 5 * 3600e3));
    expect(units.map((u) => u.id).sort()).toEqual(wialonCompany.units.map((u: any) => String(u.platform_id)).sort());
    expect(units.map((u) => u.name).sort()).toEqual(wialonCompany.units.map((u: any) => u.name).sort());
    for (const u of units) {
      expect(u.records.length).toBeGreaterThan(5);
      expect(u.records.some((r) => r.lat != null && r.lon != null)).toBe(true);
      expect(u.records.some((r) => r.speed_kmh != null && r.sats != null)).toBe(true);
      expect(u.records.some((r) => typeof r.engine_hours === 'number' && r.engine_hours > 0)).toBe(true);
      expect(u.records.some((r) => typeof r.odometer_km === 'number' && r.odometer_km > 0)).toBe(true);
      expect(u.records.some((r) => r.sensors && typeof r.sensors.fuel_level_l === 'number')).toBe(true);
      expect(u.records.some((r) => r.sensors && typeof r.sensors.rpm === 'number')).toBe(true);
      expect(u.records.some((r) => r.sensors && typeof r.sensors.coolant_temp_c === 'number')).toBe(true);
      // моточасы растут во времени (история load_interval работает)
      const hours = u.records.filter((r) => typeof r.engine_hours === 'number').map((r) => r.engine_hours as number);
      expect(Math.max(...hours)).toBeGreaterThan(Math.min(...hours));
    }
  });

  it('страница входа Wialon выдаёт токен, который принимает token/login', async () => {
    const cred = creds.find((c) => c.platform === 'wialon')!;
    const page = await simRequest(
      `${WIALON}/login.html?${new URLSearchParams({ client_id: 'ITles', lang: 'ru', redirect_uri: 'https://itles.app/app/#/connect/wialon', response_type: 'token' })}`,
    );
    expect(page.status).toBe(200);
    const html = await page.text();
    expect(html).toContain('Wialon Local — эмуляция (стенд ITles)');
    expect(html).toContain('name="redirect_uri"');
    const post = await simRequest(`${WIALON}/login.html`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        login: cred.login,
        password: cred.password,
        redirect_uri: 'https://itles.app/app/#/connect/wialon',
        client_id: 'ITles',
      }).toString(),
    });
    expect(post.status).toBe(302);
    const loc = post.headers.get('location')!;
    expect(loc.startsWith('https://itles.app/app/#/connect/wialon?')).toBe(true);
    const token = /access_token=([^&]+)/.exec(loc)![1];
    expect(token).toBe(cred.token);
    const login = await ajax('token/login', { token, fl: 1 });
    const data = await login.json();
    expect(data.eid).toBeTruthy();
    expect(data.user.nm).toBe(cred.login);
    const search = await ajax('core/search_items', { flags: 0x401 }, data.eid);
    expect((await search.json()).items).toHaveLength(3);
  });

  it('Wialon отклоняет неверный токен и сессию ошибками 8 и 1', async () => {
    const badToken = await ajax('token/login', { token: 'not-a-token' });
    expect(await badToken.json()).toEqual({ error: 8 });
    const badSid = await ajax('core/search_items', { flags: 1025 }, 'deadbeef');
    expect(await badSid.json()).toEqual({ error: 1 });
  });

  it('коннектор AEMP 2.0 получает машины, моточасы, пробег и топливо', async () => {
    const cred = creds.find((c) => c.platform === 'aemp')!;
    const units = await fetchUnits('aemp', AEMP, { username: cred.login, password: cred.password });
    expect(units.map((u) => u.id).sort()).toEqual(aempCompany.units.map((u: any) => u.uid).sort());
    for (const u of units) {
      expect(u.make).toBe('Komatsu');
      expect(u.records.some((r) => r.lat != null && r.lon != null)).toBe(true);
      expect(u.records.some((r) => typeof r.engine_hours === 'number' && r.engine_hours > 0)).toBe(true);
      expect(u.records.some((r) => typeof r.odometer_km === 'number' && r.odometer_km > 0)).toBe(true);
      expect(u.records.some((r) => r.sensors && typeof r.sensors.fuel_level_pct === 'number')).toBe(true);
      expect(u.records.some((r) => r.sensors && typeof r.sensors.fuel_used_l === 'number')).toBe(true);
    }
  });

  it('AEMP требует Basic-авторизацию и умеет отдавать XML', async () => {
    const noAuth = await simRequest(AEMP);
    expect(noAuth.status).toBe(401);
    expect(noAuth.headers.get('www-authenticate')).toBe('Basic realm="AEMP"');
    const wrong = await simRequest(AEMP, { headers: { authorization: 'Basic ' + Buffer.from('x:y').toString('base64') } });
    expect(wrong.status).toBe(401);
    const cred = creds.find((c) => c.platform === 'aemp')!;
    const xml = await simRequest(AEMP, {
      headers: { authorization: 'Basic ' + Buffer.from(`${cred.login}:${cred.password}`).toString('base64'), accept: 'application/xml' },
    });
    expect(xml.headers.get('content-type')).toContain('xml');
    const parsed = parseAempFleet(await xml.text());
    expect(parsed.units).toHaveLength(3);
    expect(parsed.next).toBeNull();
    expect(parsed.units[0].records.some((r) => typeof r.engine_hours === 'number')).toBe(true);
  });

  it('эмуляторы доступны и по префиксу /ext (локальная разработка)', async () => {
    const cred = creds.find((c) => c.platform === 'aemp')!;
    const aemp = await simRequest('http://localhost:8787/ext/aemp/Fleet/1', {
      headers: { authorization: 'Basic ' + Buffer.from(`${cred.login}:${cred.password}`).toString('base64') },
    });
    expect(aemp.status).toBe(200);
    const wialon = await simRequest('http://localhost:8787/ext/wialon/');
    expect(wialon.status).toBe(200);
    expect(await wialon.text()).toContain('Wialon Local');
  });
});
