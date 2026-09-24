// Эмуляция Wialon Local: отдаёт ровно тот набор Remote API, который разбирает
// platform/server/connectors/wialon.ts (token/login, core/search_items, messages/*, core/logout).
import { randomBytes } from 'node:crypto';
import { getDb, type Db } from '../db.js';
import { sha256, verifyPassword } from '../auth.js';
import { decryptSecret, encryptSecret } from '../secrets.js';
import { json } from '../http.js';
import { simextCompany, type SimextCompany, type SimextUnit } from './model.js';
import {
  accountByLogin,
  accountByTokenHash,
  ensureSimextSchema,
  latestSimextMessages,
  messageParams,
  messageSeconds,
  simextHistory,
  type SimextAccount,
  type SimextMessageRow,
} from './store.js';

const FLAG_LAST_POS = 0x400;
const FLAG_COUNTERS = 0x2000;

const OAUTH_KEYS = ['client_id', 'access_type', 'activation_time', 'duration', 'lang', 'flags', 'redirect_uri', 'response_type'];

// Стенд передаёт охлаждающую жидкость и питание под CAN-подобными именами; в сообщениях Wialon
// они фигурируют под ключами реестра датчиков ITles.
const PARAM_RENAME: Record<string, string> = { coolant_c: 'coolant_temp_c', pwr_v: 'battery_v' };

const esc = (v: unknown): string =>
  String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const html = (title: string, body: string, status = 200): Response =>
  new Response(
    `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
      `<title>${esc(title)}</title><style>body{font-family:system-ui,sans-serif;max-width:30rem;margin:3rem auto;padding:0 1rem;color:#111}` +
      `h1{font-size:1.25rem}code{background:#f3f4f6;padding:.1rem .3rem;border-radius:.25rem}` +
      `form{display:grid;gap:.75rem;margin-top:1rem}input,button{font:inherit;padding:.5rem .75rem}` +
      `button{background:#1d4ed8;color:#fff;border:0;border-radius:.5rem;cursor:pointer}.err{color:#b91c1c}</style></head>` +
      `<body>${body}</body></html>`,
    { status, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } },
  );

const wialonParams = (p: Record<string, unknown>): Record<string, number> => {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(p)) {
    if (typeof v !== 'number' || !Number.isFinite(v)) continue;
    out[PARAM_RENAME[k] ?? k] = v;
  }
  return out;
};

const wialonPos = (row: SimextMessageRow): Record<string, number> | undefined =>
  row.lat === null || row.lon === null
    ? undefined
    : { t: messageSeconds(row.t), y: row.lat, x: row.lon, z: row.alt ?? 0, s: row.speed_kmh ?? 0, c: row.course ?? 0, sc: row.sats ?? 0 };

const wialonMessage = (row: SimextMessageRow): Record<string, unknown> => {
  const pos = wialonPos(row);
  return {
    t: messageSeconds(row.t),
    f: pos ? 3 : 1,
    tp: 'ud',
    ...(pos ? { pos } : {}),
    p: wialonParams(messageParams(row)),
  };
};

const unitItemId = (u: SimextUnit): number => u.platform_id ?? Number(u.uid);

export async function handleWialon(req: Request, prefix = ''): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname.slice(prefix.length) || '/';
  if (path === '/') {
    return html(
      'Wialon Local — эмуляция (стенд ITles)',
      `<h1>Wialon Local — эмуляция (стенд ITles)</h1>` +
        `<p>Это не настоящий сервер Wialon: машины моделируются стендом ITles, а их данные выдаются по настоящему протоколу Wialon Remote API.</p>` +
        `<p>API: <code>${esc(prefix || '')}/wialon/ajax.html?svc=…&amp;params=…&amp;sid=…</code>; ` +
        `страница входа за токеном: <code>${esc(prefix || '')}/login.html</code>.</p>`,
    );
  }
  if (path === '/login.html') {
    if (req.method === 'POST') return loginSubmit(req, url, prefix);
    return loginPage(url.searchParams, prefix);
  }
  if (path === '/wialon/ajax.html') return ajax(req, url);
  return new Response('Не найдено', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
}

async function ajax(req: Request, url: URL): Promise<Response> {
  const db = await getDb();
  await ensureSimextSchema(db);
  let form: URLSearchParams | null = null;
  if (req.method === 'POST' && (req.headers.get('content-type') ?? '').includes('application/x-www-form-urlencoded'))
    form = new URLSearchParams(await req.text());
  const get = (k: string) => url.searchParams.get(k) ?? form?.get(k) ?? null;
  const svc = get('svc') ?? '';
  const sid = get('sid') ?? '';
  let spec: any = {};
  try {
    spec = JSON.parse(get('params') ?? '{}');
  } catch {
    return json({ error: 4 });
  }
  if (!svc) return json({ error: 4 });
  if (svc === 'token/login') {
    const token = typeof spec.token === 'string' ? spec.token : '';
    const acc = token ? await accountByTokenHash(db, sha256(token)) : null;
    if (!acc) return json({ error: 8 });
    // Идентификатор сессии = хэш токена: проверка сессии остаётся stateless (важно для serverless).
    return json({ eid: sha256(token), user: { id: 1, nm: acc.login, cls: 1, fl: 4, bact: 0 } });
  }
  const acc = await accountByTokenHash(db, sid);
  if (!acc) return json({ error: 1 });
  const company = simextCompany(acc.company_id);
  if (!company) return json({ error: 1 });
  if (svc === 'core/search_items') return json(await searchItems(db, company, Number(spec?.flags) || 0));
  if (svc === 'messages/load_interval') return json(await loadInterval(db, company, spec));
  if (svc === 'messages/unload' || svc === 'core/logout') return json({});
  return json({ error: 4 });
}

async function searchItems(db: Db, company: SimextCompany, flags: number): Promise<any> {
  const last = await latestSimextMessages(db, company.id);
  const units = [...company.units].sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  const items = units.map((u) => {
    const row = last.get(u.uid);
    // mu = 0 (метрическая система): cnm приходит в км, cneh — в моточасах, как их читает ITles.
    const item: any = { id: unitItemId(u), nm: u.name, mu: 0, uid: u.uid, cls: 1 };
    if (flags & FLAG_LAST_POS && row) {
      const pos = wialonPos(row);
      if (pos) item.pos = pos;
      item.lmsg = wialonMessage(row);
    }
    if (flags & FLAG_COUNTERS && row) {
      const p = messageParams(row);
      if (typeof p.engine_hours === 'number') item.cneh = p.engine_hours;
      if (typeof p.odometer_km === 'number') item.cnm = p.odometer_km;
    }
    return item;
  });
  return { items, total: items.length };
}

async function loadInterval(db: Db, company: SimextCompany, spec: any): Promise<any> {
  const itemId = Number(spec?.itemId);
  const unit = company.units.find((u) => unitItemId(u) === itemId);
  if (!unit) return json({ error: 4 });
  const from = Number(spec?.timeFrom) || 0;
  const to = Number(spec?.timeTo) || Math.floor(Date.now() / 1000);
  const rows = await simextHistory(db, company.id, unit.uid, from, to);
  return { count: rows.length, messages: rows.map(wialonMessage) };
}

const hidden = (fields: URLSearchParams): string =>
  OAUTH_KEYS.map((k) => {
    const v = fields.get(k);
    return v === null ? '' : `<input type="hidden" name="${k}" value="${esc(v)}">`;
  }).join('');

function loginPage(fields: URLSearchParams, prefix: string, error?: string, status = 200): Response {
  const action = `${prefix}/login.html`;
  return html(
    'Wialon Local — эмуляция (стенд ITles)',
    `<h1>Wialon Local — эмуляция (стенд ITles)</h1>` +
      `<p>Страница выдаёт токен только для чтения к данным эмулируемого парка на стенде ITles. ` +
      `Введите логин и пароль, выданные при установке стенда.</p>` +
      (error ? `<p class="err">${esc(error)}</p>` : '') +
      `<form method="post" action="${esc(action)}">${hidden(fields)}` +
      `<label>Логин<input name="login" required autofocus></label>` +
      `<label>Пароль<input name="password" type="password" required></label>` +
      `<button>Войти и выдать токен</button></form>`,
  );
}

async function loginSubmit(req: Request, url: URL, prefix: string): Promise<Response> {
  const form = new URLSearchParams(await req.text());
  const login = (form.get('login') ?? '').trim();
  const password = form.get('password') ?? '';
  const redirect = form.get('redirect_uri') ?? url.searchParams.get('redirect_uri') ?? '';
  if (!redirect)
    return html('Wialon Local — эмуляция', '<h1>Wialon Local — эмуляция (стенд ITles)</h1><p class="err">Не указан redirect_uri.</p>');
  const db = await getDb();
  await ensureSimextSchema(db);
  const acc = await accountByLogin(db, 'wialon', login);
  if (!acc || !password || !(await verifyPassword(password, acc.pass_hash)))
    return loginPage(form, prefix, 'Неверный логин или пароль.', 401);
  const token = await accountToken(db, acc);
  const sep = redirect.includes('?') ? '&' : '?';
  return new Response(null, {
    status: 302,
    headers: { location: `${redirect}${sep}access_token=${encodeURIComponent(token)}&user_name=${encodeURIComponent(login)}` },
  });
}

/** Токен хранится зашифрованным, чтобы OAuth-вход возвращал тот же токен, что напечатан при установке. */
async function accountToken(db: Db, acc: SimextAccount): Promise<string> {
  if (acc.token_enc) {
    try {
      return decryptSecret(acc.token_enc);
    } catch {
      // ключ APP_SECRET сменился: перевыпускаем токен
    }
  }
  const token = randomBytes(36).toString('hex');
  await db.query(`update simext_accounts set token_hash = $2, token_enc = $3, updated_at = now() where company_id = $1`, [
    acc.company_id,
    sha256(token),
    encryptSecret(token),
  ]);
  return token;
}
