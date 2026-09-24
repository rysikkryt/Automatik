export const TOKEN_KEY = 'itles_token';
export const API_KEY = 'itles_api';
export const PROD_API = 'https://itles.vercel.app';

/** Same origin in the browser; native shells (capacitor://, file://) talk to the configured server. */
export function apiBase(): string {
  const o = localStorage.getItem(API_KEY);
  if (o) return o.replace(/\/+$/, '');
  if (!location.protocol.startsWith('http') || location.hostname === 'localhost' && location.port === '') return PROD_API;
  return '';
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T = any>(method: string, path: string, body?: unknown, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { 'x-itles-client': 'web' };
  if (body !== undefined) headers['content-type'] = 'application/json';
  const tok = token === undefined ? localStorage.getItem(TOKEN_KEY) : token;
  if (tok) headers.authorization = `Bearer ${tok}`;
  let r: Response;
  try {
    r = await fetch(apiBase() + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, 'offline', 'Нет связи с сервером');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data.error ?? 'error', data.message ?? `Ошибка ${r.status}`);
  return data as T;
}

export const CATEGORY_RU: Record<string, string> = {
  harvester: 'Харвестер',
  forwarder: 'Форвардер',
  skidder: 'Трелёвочный трактор',
  timber_truck: 'Лесовоз',
  tractor: 'Трактор',
  combine: 'Зерноуборочный комбайн',
  forage_harvester: 'Кормоуборочный комбайн',
  sprayer: 'Опрыскиватель',
  excavator: 'Экскаватор',
  loader: 'Погрузчик',
  dozer: 'Бульдозер',
  grader: 'Автогрейдер',
  roller: 'Каток',
  crane: 'Кран',
  telehandler: 'Телескопический погрузчик',
  dump_truck: 'Карьерный самосвал',
  truck: 'Грузовик',
  drill: 'Буровой станок',
  other: 'Другая техника',
};

export const METHOD_RU: Record<string, string> = {
  ecu: 'из блока управления (CAN)',
  tracker: 'счётчик трекера',
  platform: 'счётчик платформы',
  device: 'оценка телефона',
  reading: 'показание счётчика',
  gnss: 'по ГНСС',
  'gnss+reading': 'счётчик + ГНСС',
};

export const SOURCE_RU: Record<string, string> = {
  tracker: 'Трекер',
  phone: 'Телефон в кабине',
  traccar: 'Traccar',
  wialon: 'Wialon',
  aemp: 'ISO 15143-3',
  manual: 'Вручную',
};

export function ago(t: number | null | undefined, now = Date.now()): string {
  if (!t) return 'нет данных';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return 'только что';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} мин назад`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} ч назад`;
  return `${Math.round(h / 24)} дн назад`;
}

export const fmt = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });
