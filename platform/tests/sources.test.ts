import { beforeAll, describe, expect, it } from 'vitest';
import { call, iso } from './helpers.js';

process.env.DATABASE_URL = process.env.TEST_DATABASE_URL ?? 'pglite:memory';
process.env.SETUP_KEY = 'test-setup-key-0123456789';
process.env.GATEWAY_TOKEN = 'gw_test_token_0123456789abcdef';
process.env.CRON_SECRET = 'cron-secret-test';

let owner = '';
let machine = '';

describe('data source lifecycle: disable → enable → delete', () => {
  beforeAll(async () => {
    const st = await call('POST', '/api/setup', { setup_key: process.env.SETUP_KEY, login: 'sources-owner', password: 'secret-password' });
    expect(st.status).toBe(201);
    owner = st.data.token;
    const o = await call('POST', '/api/orgs', { kind: 'customer', name: 'Клиент для источников' }, owner);
    expect(o.status).toBe(201);
    const m = await call('POST', '/api/machines', { org_id: o.data.org.id, name: 'Машина А', category: 'tractor' }, owner);
    expect(m.status).toBe(201);
    machine = m.data.machine.id;
  });

  it('disabling a tracker frees the IMEI and the gateway answers unknown_device', async () => {
    const s = await call('POST', `/api/machines/${machine}/sources`, { kind: 'tracker', external_id: '868204005185901' }, owner);
    expect(s.status).toBe(201);
    const ok = await call('POST', '/api/ingest', { records: [{ ext_id: '868204005185901', t: iso(60e3), lat: 55.7, lon: 37.6 }] }, process.env.GATEWAY_TOKEN);
    expect(ok.data.results[0].status).toBe('ok');
    expect((await call('POST', `/api/sources/${s.data.source_id}/disable`, {}, owner)).status).toBe(200);
    const det = (await call('GET', `/api/machines/${machine}`, undefined, owner)).data;
    const src = det.sources.find((x: any) => x.id === s.data.source_id);
    expect(src.disabled_at).toBeTruthy();
    expect(src.external_id).toBeNull();
    const after = await call('POST', '/api/ingest', { records: [{ ext_id: '868204005185901', t: iso(30e3), lat: 55.7, lon: 37.6 }] }, process.env.GATEWAY_TOKEN);
    expect(after.data.results[0].status).toBe('unknown_device');
  });

  it('enabling restores the tracker and data is accepted again', async () => {
    const s = await call('POST', `/api/machines/${machine}/sources`, { kind: 'tracker', external_id: '868204005185902' }, owner);
    await call('POST', `/api/sources/${s.data.source_id}/disable`, {}, owner);
    expect((await call('POST', `/api/sources/${s.data.source_id}/enable`, {}, owner)).status).toBe(200);
    const ok = await call('POST', '/api/ingest', { records: [{ ext_id: '868204005185902', t: iso(10e3), lat: 55.71, lon: 37.61 }] }, process.env.GATEWAY_TOKEN);
    expect(ok.data.results[0].status).toBe('ok');
    expect(ok.data.results[0].positions).toBe(1);
  });

  it('enable is a 409 when another active source took the identifier meanwhile', async () => {
    const s = await call('POST', `/api/machines/${machine}/sources`, { kind: 'tracker', external_id: '868204005185903' }, owner);
    await call('POST', `/api/sources/${s.data.source_id}/disable`, {}, owner);
    const other = await call('POST', `/api/machines/${machine}/sources`, { kind: 'tracker', external_id: '868204005185903' }, owner);
    expect(other.status).toBe(201);
    const conflict = await call('POST', `/api/sources/${s.data.source_id}/enable`, {}, owner);
    expect(conflict.status).toBe(409);
  });

  it('a re-enabled phone gets a fresh pairing code that works', async () => {
    const p = await call('POST', `/api/machines/${machine}/sources`, { kind: 'phone' }, owner);
    expect(p.status).toBe(201);
    await call('POST', `/api/sources/${p.data.source_id}/disable`, {}, owner);
    const en = await call('POST', `/api/sources/${p.data.source_id}/enable`, {}, owner);
    expect(en.status).toBe(200);
    expect(String(en.data.pairing_code)).toMatch(/^\d{6}$/);
    const pair = await call('POST', '/api/devices/enroll', { code: en.data.pairing_code });
    expect(pair.status).toBe(201);
    const asDevice = await call('POST', '/api/ingest', { records: [{ t: iso(5e3), lat: 55.7, lon: 37.6 }] }, pair.data.token);
    expect(asDevice.status).toBe(200);
    // the existing paired token dies with the phone disable
    await call('POST', `/api/sources/${p.data.source_id}/disable`, {}, owner);
    expect((await call('POST', '/api/ingest', { records: [{ t: iso(5e3), lat: 55.7, lon: 37.6 }] }, pair.data.token)).status).toBe(401);
  });

  it('deleting hides the source everywhere and keeps the received data', async () => {
    const s = await call('POST', `/api/machines/${machine}/sources`, { kind: 'tracker', external_id: '868204005185904' }, owner);
    await call(
      'POST',
      '/api/ingest',
      { records: [{ ext_id: '868204005185904', t: iso(200e3), lat: 55.72, lon: 37.62, engine_hours: 100, engine_hours_method: 'ecu' }] },
      process.env.GATEWAY_TOKEN,
    );
    expect((await call('DELETE', `/api/sources/${s.data.source_id}`, undefined, owner)).status).toBe(200);
    const det = (await call('GET', `/api/machines/${machine}`, undefined, owner)).data;
    expect(det.sources.map((x: any) => x.id)).not.toContain(s.data.source_id);
    const after = await call('POST', '/api/ingest', { records: [{ ext_id: '868204005185904', t: iso(100e3), lat: 55.72, lon: 37.62 }] }, process.env.GATEWAY_TOKEN);
    expect(after.data.results[0].status).toBe('unknown_device');
    // counters of a deleted source no longer surface in machine views
    const counters = await call('GET', `/api/machines/${machine}/counters?metric=engine_hours&days=7`, undefined, owner);
    expect(counters.data.series.map((x: any) => x.source_id)).not.toContain(s.data.source_id);
  });
});
