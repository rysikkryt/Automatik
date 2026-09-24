import type { Me } from '../main';
import { go } from '../main';
import { api, ago, fmt } from '../api';
import { ErrorLine, useAsync } from '../ui';
import { OilHowTo, STATUS_CLS, STATUS_RU, StatusDot, fmtSensor } from '../oil';

const COLS = ['oil_level_pct', 'oil_temp_c', 'hyd_temp_c', 'oil_pressure_kpa', 'oil_water_aw'] as const;
const HEAD: Record<string, string> = { oil_level_pct: 'Уровень', oil_temp_c: 'T масла', hyd_temp_c: 'T гидравлики', oil_pressure_kpa: 'Давление', oil_water_aw: 'Вода, aw' };

export function Oil({ me }: { me: Me }) {
  const res = useAsync(() => api('GET', '/api/oil/overview'), []);
  const rows: any[] = res.data?.machines ?? [];
  const crit = rows.filter((r) => r.oil.status === 'crit').length;
  const warn = rows.filter((r) => r.oil.status === 'warn').length;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Масло</h1>
        <p className="text-sm text-muted-foreground">
          {rows.length} машин с датчиками масла · критично {crit} · внимание {warn}. Пределы — ориентиры по умолчанию; расход считается по уровню и моточасам.
        </p>
      </div>
      <ErrorLine e={res.error} />
      {!res.loading && rows.length === 0 ? (
        <div className="card p-6">
          <OilHowTo />
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b border-border text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Машина</th>
                <th className="px-4 py-3">Статус</th>
                {COLS.map((k) => (
                  <th key={k} className="px-4 py-3">
                    {HEAD[k]}
                  </th>
                ))}
                <th className="px-4 py-3">Расход, %/100 ч</th>
                <th className="px-4 py-3">Доливы 30 дн</th>
                <th className="px-4 py-3">Обновлено</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="cursor-pointer border-b border-border last:border-0 hover:bg-accent" onClick={() => go('#/machine/' + r.id)}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.name}</div>
                    {me.org_kind !== 'customer' && <div className="text-xs text-muted-foreground">{r.org_name}</div>}
                  </td>
                  <td className="px-4 py-3">{r.oil.status ? <span className={`badge ${STATUS_CLS[r.oil.status]}`}>{STATUS_RU[r.oil.status]}</span> : '—'}</td>
                  {COLS.map((k) => {
                    const v = r.oil.values[k];
                    return (
                      <td key={k} className="px-4 py-3 tabular-nums">
                        <span className="inline-flex items-center gap-1.5">
                          {v && <StatusDot s={v.status} />}
                          {fmtSensor(k, v?.value)}
                        </span>
                      </td>
                    );
                  })}
                  <td className="px-4 py-3 tabular-nums">{r.consumption_pct_per_100h === null ? '—' : fmt(r.consumption_pct_per_100h, 1)}</td>
                  <td className="px-4 py-3 tabular-nums">{r.topups_30d ?? '—'}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{ago(r.oil.t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
