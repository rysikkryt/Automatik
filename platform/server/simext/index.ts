// Диспетчер эмулируемых внешних платформ: свои домены (x-forwarded-host) и путь /ext/* для локальной
// разработки и тестов; всё остальное уходит в основное приложение ITles.
import { handle } from '../app.js';
import { json } from '../http.js';
import { simextHosts } from './model.js';
import { handleWialon } from './wialon.js';
import { handleAemp } from './aemp.js';

function requestHost(req: Request): string {
  const xf = req.headers.get('x-forwarded-host');
  const raw = (xf ? xf.split(',')[0] : req.headers.get('host')) || new URL(req.url).host;
  try {
    return new URL(`http://${raw.trim().toLowerCase()}`).hostname;
  } catch {
    return '';
  }
}

export async function handleWithSimext(req: Request): Promise<Response> {
  const path = new URL(req.url).pathname;
  if (path === '/api' || path.startsWith('/api/')) return handle(req);
  const byHost = simextHosts.get(requestHost(req));
  try {
    if (byHost?.platform === 'wialon') return await handleWialon(req, '');
    if (byHost?.platform === 'aemp') return await handleAemp(req, '');
    if (path.startsWith('/ext/wialon')) return await handleWialon(req, '/ext/wialon');
    if (path.startsWith('/ext/aemp')) return await handleAemp(req, '/ext/aemp');
  } catch (e) {
    console.error('simext', e);
    return json({ error: 'internal', message: 'Внутренняя ошибка эмуляции' }, 500);
  }
  return handle(req);
}
