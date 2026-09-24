import { useEffect, useState } from 'react';
import { api, API_KEY, TOKEN_KEY } from '../api';
import { ErrorLine } from '../ui';
import { ThemeToggle } from '../main-toggle';

export function Login({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<'login' | 'redeem' | 'setup'>('login');
  const [f, setF] = useState<Record<string, string>>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  useEffect(() => {
    api('GET', '/api/setup/status')
      .then((r) => {
        setNeedsSetup(r.needs_setup);
        if (r.needs_setup) setMode('setup');
      })
      .catch(() => {});
  }, []);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const path = mode === 'login' ? '/api/auth/login' : mode === 'redeem' ? '/api/auth/redeem' : '/api/setup';
      const r = await api(mode === 'login' ? 'POST' : 'POST', path, { ...f, login: (f.login ?? '').trim().toLowerCase() }, null);
      localStorage.setItem(TOKEN_KEY, r.token);
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="relative flex min-h-full flex-col items-center justify-center gap-6 bg-background p-4 py-10">
      <div className="absolute right-4 top-4"><ThemeToggle /></div>
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-7 shadow-2xl">
        <div className="flex items-center gap-3">
          <img src="../favicon.svg" className="h-10 w-10" alt="" />
          <div>
            <div className="text-lg font-bold">ITles</div>
            <div className="text-xs text-muted-foreground">моточасы · пробег · местоположение</div>
          </div>
        </div>
        <div className="flex gap-1 rounded-xl bg-muted p-1 text-sm">
          {(needsSetup ? [['setup', 'Первый запуск']] : [['login', 'Вход'], ['redeem', 'У меня есть код']]).map(([m, t]) => (
            <button type="button" key={m} onClick={() => setMode(m as any)} className={`flex-1 rounded-md py-1.5 font-medium ${mode === m ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'}`}>
              {t}
            </button>
          ))}
        </div>
        {mode === 'setup' && (
          <>
            <p className="text-xs text-muted-foreground">Создание учётной записи FUCHS — главной организации системы. Ключ установки задан на сервере (SETUP_KEY).</p>
            <div>
              <label className="label">Ключ установки</label>
              <input className="input" value={f.setup_key ?? ''} onChange={set('setup_key')} required />
            </div>
            <div>
              <label className="label">Название организации</label>
              <input className="input" value={f.org_name ?? 'FUCHS'} onChange={set('org_name')} />
            </div>
          </>
        )}
        {mode === 'redeem' && (
          <div>
            <label className="label">Код приглашения</label>
            <input className="input font-mono uppercase" placeholder="XXXX-XXXX" value={f.code ?? ''} onChange={set('code')} required />
          </div>
        )}
        <div>
          <label className="label">{mode === 'login' ? 'Логин' : 'Придумайте логин'}</label>
          <input className="input" autoComplete="username" value={f.login ?? ''} onChange={set('login')} required />
        </div>
        <div>
          <label className="label">Пароль</label>
          <input className="input" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={f.password ?? ''} onChange={set('password')} required minLength={mode === 'login' ? 1 : 8} />
        </div>
        <ErrorLine e={err} />
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? 'Подождите…' : mode === 'login' ? 'Войти' : mode === 'redeem' ? 'Создать учётную запись' : 'Создать'}
        </button>
        <div className="flex justify-between text-xs text-muted-foreground">
          <a className="hover:text-primary" href="#/cab">
            Режим «Телефон в кабине» →
          </a>
          <button
            type="button"
            className="hover:text-primary"
            onClick={() => {
              const v = prompt('Адрес сервера (пусто — по умолчанию)', localStorage.getItem(API_KEY) ?? '');
              if (v === null) return;
              if (v.trim()) localStorage.setItem(API_KEY, v.trim());
              else localStorage.removeItem(API_KEY);
              location.reload();
            }}
          >
            Сервер
          </button>
        </div>
      </form>
    </div>
  );
}
