import type { IncomingMessage, ServerResponse } from 'node:http';

/** Node http ⇄ Web Request/Response, shared by the VPS server and the Vercel function. */
export async function toWebRequest(req: IncomingMessage, defaultProto = 'http'): Promise<Request> {
  const proto = (req.headers['x-forwarded-proto'] as string | undefined)?.split(',')[0] ?? defaultProto;
  const url = new URL(req.url ?? '/', `${proto}://${req.headers.host ?? 'localhost'}`);
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (v !== undefined) headers.set(k, Array.isArray(v) ? v.join(', ') : v);
  let body: Uint8Array | undefined;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const c of req) {
      size += (c as Buffer).length;
      if (size > 12_000_000) throw new Error('body too large');
      chunks.push(c as Buffer);
    }
    body = new Uint8Array(Buffer.concat(chunks));
  }
  return new Request(url, { method: req.method, headers, body: body as unknown as BodyInit | undefined });
}

export async function sendWebResponse(response: Response, res: ServerResponse): Promise<void> {
  const out: Record<string, string> = {};
  response.headers.forEach((v, k) => (out[k] = v));
  res.writeHead(response.status, out);
  res.end(Buffer.from(await response.arrayBuffer()));
}
