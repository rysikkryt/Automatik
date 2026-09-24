// Приём данных стенда: модели машин передают показания по внутреннему контракту стенда,
// эмуляторы Wialon и AEMP 2.0 затем раздают их внешним протоколам.
import { gateway, router } from '../core.js';
import { bad, json, readJson } from '../http.js';
import { simextCompany } from './model.js';
import { ensureSimextSchema, insertSimextMessages, type SimextPushRow } from './store.js';

const MAX_RECORDS = 5000;

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

router.on('POST', '/api/simext/push', async (c) => {
  gateway(c);
  const b = await readJson<any>(c.req);
  const company = typeof b?.company === 'string' ? simextCompany(b.company) : undefined;
  if (!company) throw bad('unknown_company', 'Нет эмулируемой компании с таким идентификатором');
  if (!Array.isArray(b.records)) throw bad('bad_records', 'Нужен массив records');
  if (b.records.length > MAX_RECORDS) throw bad('too_many_records', `Не больше ${MAX_RECORDS} записей за один запрос`);
  const uids = new Set(company.units.map((u) => u.uid));
  const unknown = new Set<string>();
  const rows: SimextPushRow[] = [];
  let invalid = 0;
  for (const r of b.records) {
    const unit = typeof r?.unit === 'string' ? r.unit : null;
    if (!unit || !uids.has(unit)) {
      if (unit) unknown.add(unit);
      invalid++;
      continue;
    }
    const t = num(r.t);
    if (t === null || t < 1e9 || t > Date.now() / 1000 + 86_400) {
      invalid++;
      continue;
    }
    const params: Record<string, unknown> = {};
    if (r.params && typeof r.params === 'object') {
      for (const [k, v] of Object.entries(r.params)) if (typeof v === 'number' && Number.isFinite(v)) params[k] = v;
    }
    const sats = num(r.sats);
    rows.push({
      unit,
      t: new Date(t * 1000).toISOString(),
      lat: num(r.lat),
      lon: num(r.lon),
      speed: num(r.speed),
      course: num(r.course),
      alt: num(r.alt),
      sats: sats === null ? null : Math.round(sats),
      params,
    });
  }
  await ensureSimextSchema(c.db);
  const stored = await insertSimextMessages(c.db, company.id, rows);
  // Раз в ~20 выгрузок подчищаем данные старше 35 дней, чтобы таблица не росла бесконечно.
  if (Math.random() < 0.05) await c.db.query(`delete from simext_messages where t < now() - interval '35 days'`);
  return json({ stored, duplicates: rows.length - stored, unknown_units: [...unknown], invalid });
});
