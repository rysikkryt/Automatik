// Печать доступов эмулируемых платформ: DATABASE_URL передаётся вызывающим, например
//   DATABASE_URL=... npx tsx platform/scripts/simext-credentials.ts
// На stdout — по одной JSON-строке на компанию (логин, пароль, токен Wialon).
import { pathToFileURL } from 'node:url';
import { openDb } from '../server/db.js';
import { upsertSimextCredentials } from '../server/simext/credentials.js';

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error('Нужна переменная окружения DATABASE_URL');
    process.exitCode = 1;
    return;
  }
  const db = await openDb(url);
  try {
    for (const cred of await upsertSimextCredentials(db)) console.log(JSON.stringify(cred));
  } finally {
    await db.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
