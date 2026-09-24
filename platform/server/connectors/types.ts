import type { IngestRecord } from '../ingest.js';

export interface RemoteUnit {
  id: string;
  name: string;
  make?: string | null;
  model?: string | null;
  records: IngestRecord[];
}

export class ConnectorError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function fetchJson(url: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<any> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), init.timeoutMs ?? 20_000);
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: ctl.signal });
  } catch (e: any) {
    throw new ConnectorError('unreachable', `Сервер ${new URL(url).host} недоступен: ${e?.name === 'AbortError' ? 'таймаут' : e?.message}`);
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  if (res.status === 401 || res.status === 403)
    throw new ConnectorError('auth', `Сервер ${new URL(url).host} отклонил доступ (HTTP ${res.status})`);
  if (!res.ok) throw new ConnectorError('http', `HTTP ${res.status} от ${new URL(url).host}: ${text.slice(0, 200)}`);
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function trimBase(u: string): string {
  const url = new URL(u.trim());
  if (url.protocol !== 'https:' && url.protocol !== 'http:') throw new ConnectorError('config', 'Адрес должен начинаться с https://');
  return url.origin + url.pathname.replace(/\/+$/, '');
}
