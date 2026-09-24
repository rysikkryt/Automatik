import { handle } from '../server/app.js';

export async function call(method: string, path: string, body?: unknown, token?: string, extra: Record<string, string> = {}) {
  const headers: Record<string, string> = { 'content-type': 'application/json', ...extra };
  if (token) headers.authorization = `Bearer ${token}`;
  const res = await handle(
    new Request('http://localhost' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }),
  );
  const text = await res.text();
  let data: any = text;
  try {
    data = JSON.parse(text);
  } catch {
    // non-JSON body (photo)
  }
  return { status: res.status, data, headers: res.headers };
}

export function iso(msAgo: number, now = Date.now()) {
  return new Date(now - msAgo).toISOString();
}
