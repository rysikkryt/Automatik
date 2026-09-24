import type { IncomingMessage, ServerResponse } from 'node:http';
import { handleWithSimext } from '../server/simext/index.js';
import { sendWebResponse, toWebRequest } from '../server/node-adapter.js';

/** Vercel Build Output API function (classic Node signature, works with any launcher). */
export default async function handler(req: IncomingMessage, res: ServerResponse) {
  await sendWebResponse(await handleWithSimext(await toWebRequest(req, 'https')), res);
}
