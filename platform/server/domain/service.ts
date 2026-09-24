export interface ServiceItemIn {
  id: string;
  item: string;
  interval_h: number;
  last_done_h: number;
  volume_l?: number | null;
  product?: string | null;
}

export interface ServiceForecast extends ServiceItemIn {
  due_at_h: number;
  remaining_h: number;
  status: 'overdue' | 'soon' | 'ok' | 'unknown';
  due_date: string | null;
}

/**
 * Next service by engine hours. avgDailyH comes from the machine's own history (daily hour
 * deltas over the last 30 days); without history only the remaining hours are reported.
 */
export function forecast(items: ServiceItemIn[], currentH: number | null, avgDailyH: number | null, now = new Date()): ServiceForecast[] {
  return items.map((it) => {
    const due = it.last_done_h + it.interval_h;
    if (currentH === null) return { ...it, due_at_h: due, remaining_h: NaN, status: 'unknown', due_date: null };
    const remaining = due - currentH;
    let dueDate: string | null = null;
    if (avgDailyH && avgDailyH > 0.05 && remaining > 0) {
      const d = new Date(now.getTime() + (remaining / avgDailyH) * 86400e3);
      dueDate = d.toISOString().slice(0, 10);
    }
    const soonH = Math.max(0.1 * it.interval_h, avgDailyH ? avgDailyH * 7 : 0);
    const status = remaining <= 0 ? 'overdue' : remaining <= soonH ? 'soon' : 'ok';
    return { ...it, due_at_h: due, remaining_h: remaining, status, due_date: dueDate };
  });
}
