/**
 * Issues real passwords for every demo account and prints one JSON line per account:
 *   DATABASE_URL=postgres://... npx tsx scripts/demo-credentials.ts
 * Run inside a private channel (the passwords are valid credentials).
 */
import { randomInt } from 'node:crypto';
import { getDb } from '../server/db.js';
import { setDemoPasswords } from '../server/demo.js';
import { BLOCKS, CAP_LABELS, ROLES, effectiveBlocks, legacyRole } from '../server/domain/roles.js';

const url = process.env.DATABASE_URL;
if (!url) throw new Error('DATABASE_URL is not set');

// readable: no lookalikes (0/o/1/l), lowercase letters and digits, 4×4 groups
const ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';
const newPassword = () =>
  Array.from({ length: 3 }, () =>
    Array.from({ length: 4 }, () => ALPHABET[randomInt(ALPHABET.length)]).join(''),
  ).join('-');

const db = await getDb(url);
const passwords = new Map<string, string>();
await db.tx(async (t) => {
  await setDemoPasswords(t, (login) => {
    const pw = newPassword();
    passwords.set(login, pw);
    return pw;
  });
  const rows = await t.query<any>(
    `select u.login, u.role, u.label, u.blocks, u.machine_ids, o.kind as org_kind, o.name as org_name
       from users u join orgs o on o.id = u.org_id
      where u.protected and o.is_demo and not u.disabled and u.deleted_at is null and o.deleted_at is null
      order by u.login`,
  );
  for (const row of rows.rows) {
    const role = legacyRole(row.role, row.org_kind);
    let machines: string[] | null = null;
    if (Array.isArray(row.machine_ids) && row.machine_ids.length) {
      const named = await t.query<{ id: string; name: string }>(`select id, name from machines where id = any($1::text[])`, [row.machine_ids]);
      const byId = new Map(named.rows.map((m) => [m.id, m.name]));
      machines = row.machine_ids.map((id: string) => byId.get(id) ?? id);
    }
    process.stdout.write(
      JSON.stringify({
        login: row.login,
        password: passwords.get(row.login),
        role,
        role_label: ROLES[role].label,
        org_name: row.org_name,
        org_kind: row.org_kind,
        caps: ROLES[role].caps.map((c) => CAP_LABELS[c]),
        blocks: effectiveBlocks(role, row.blocks).map((b) => BLOCKS[b].label),
        machines,
      }) + '\n',
    );
  }
});
await db.close();
