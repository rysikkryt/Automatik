// Учётные данные эмулируемых платформ: логин/пароль (и токен Wialon) генерируются при установке,
// в базе остаются только хэши; открытый токен хранится зашифрованным, чтобы страница входа OAuth
// возвращала тот же токен, что напечатан в выдаче scripts/simext-credentials.ts.
import { randomBytes, randomInt } from 'node:crypto';
import type { Db } from '../db.js';
import { hashPassword, sha256 } from '../auth.js';
import { encryptSecret } from '../secrets.js';
import { SIMEXT_COMPANIES, type SimextCompany } from './model.js';
import { ensureSimextSchema } from './store.js';

export interface SimextCredential {
  company: string;
  name: string;
  platform: string;
  url: string;
  login: string;
  password: string;
  token?: string;
}

const ALPHABET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

const randomPassword = (): string => {
  let s = '';
  for (let i = 0; i < 16; i++) s += ALPHABET[randomInt(ALPHABET.length)];
  return s;
};

/** 72 строчных шестнадцатеричных символа — как у настоящих токенов Wialon. */
export const newWialonToken = (): string => randomBytes(36).toString('hex');

export async function upsertSimextCredentials(db: Db, companies: SimextCompany[] = SIMEXT_COMPANIES): Promise<SimextCredential[]> {
  await ensureSimextSchema(db);
  const out: SimextCredential[] = [];
  for (const c of companies) {
    const login = c.id;
    const password = randomPassword();
    const passHash = await hashPassword(password);
    let token: string | undefined;
    if (c.platform === 'wialon') {
      token = newWialonToken();
      await db.query(
        `insert into simext_accounts (company_id, platform, login, pass_hash, token_hash, token_enc, updated_at)
         values ($1, $2, $3, $4, $5, $6, now())
         on conflict (company_id) do update set platform = $2, login = $3, pass_hash = $4, token_hash = $5, token_enc = $6, updated_at = now()`,
        [c.id, c.platform, login, passHash, sha256(token), encryptSecret(token)],
      );
    } else {
      await db.query(
        `insert into simext_accounts (company_id, platform, login, pass_hash, token_hash, updated_at)
         values ($1, $2, $3, $4, null, now())
         on conflict (company_id) do update set platform = $2, login = $3, pass_hash = $4, token_hash = null, token_enc = null, updated_at = now()`,
        [c.id, c.platform, login, passHash],
      );
    }
    out.push({ company: c.id, name: c.name, platform: c.platform, url: c.base_url, login, password, ...(token ? { token } : {}) });
  }
  return out;
}
