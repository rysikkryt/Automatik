export class HttpError extends Error {
  constructor(
    public status: number,
    public code: string,
    message?: string,
  ) {
    super(message ?? code);
  }
}

export const bad = (code: string, message?: string) => new HttpError(400, code, message);
export const forbidden = (message = 'Недостаточно прав') => new HttpError(403, 'forbidden', message);
export const notFound = (message = 'Не найдено') => new HttpError(404, 'not_found', message);

export const CORS_HEADERS: Record<string, string> = {
  // Bearer-token clients (Android/Windows apps, gateway). Cookies are never sent cross-origin
  // because Allow-Credentials is not set, so '*' does not expose cookie sessions.
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  'access-control-allow-headers': 'authorization, content-type, x-itles-client',
  'access-control-max-age': '86400',
};

export function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...CORS_HEADERS, ...headers },
  });
}

export async function readJson<T = any>(req: Request, maxBytes = 5_000_000): Promise<T> {
  const len = Number(req.headers.get('content-length') ?? '0');
  if (len > maxBytes) throw new HttpError(413, 'too_large');
  const text = await req.text();
  if (text.length > maxBytes) throw new HttpError(413, 'too_large');
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw bad('invalid_json', 'Тело запроса не является JSON');
  }
}

export type RouteHandler<C> = (ctx: C, params: Record<string, string>) => Promise<Response>;

export class Router<C> {
  private routes: Array<{ method: string; re: RegExp; keys: string[]; h: RouteHandler<C> }> = [];

  on(method: string, pattern: string, h: RouteHandler<C>): this {
    const keys: string[] = [];
    const re = new RegExp(
      '^' +
        pattern.replace(/:[a-zA-Z_]+/g, (m) => {
          keys.push(m.slice(1));
          return '([^/]+)';
        }) +
        '/?$',
    );
    this.routes.push({ method, re, keys, h });
    return this;
  }

  match(method: string, path: string): { h: RouteHandler<C>; params: Record<string, string> } | 'method' | null {
    let pathMatched = false;
    for (const r of this.routes) {
      const m = r.re.exec(path);
      if (!m) continue;
      pathMatched = true;
      if (r.method !== method) continue;
      const params: Record<string, string> = {};
      r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      return { h: r.h, params };
    }
    return pathMatched ? 'method' : null;
  }
}
