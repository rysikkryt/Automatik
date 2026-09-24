/** Durable outbox in IndexedDB: records survive app restarts and days without coverage. */
const DB_NAME = 'itles-cab';
const STORE = 'outbox';

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { autoIncrement: true });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

let dbp: Promise<IDBDatabase> | null = null;
const db = () => (dbp ??= open());

function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  return db().then(
    (d) =>
      new Promise((resolve, reject) => {
        const t = d.transaction(STORE, mode);
        const req = fn(t.objectStore(STORE));
        t.oncomplete = () => resolve(req ? (req as IDBRequest<T>).result : undefined);
        t.onerror = () => reject(t.error);
      }),
  );
}

export const push = (rec: unknown) => tx('readwrite', (s) => s.add(rec)).then(() => undefined);
export const count = () => tx<number>('readonly', (s) => s.count()).then((n) => n ?? 0);

export async function peek(limit: number): Promise<Array<{ key: IDBValidKey; rec: any }>> {
  const d = await db();
  return new Promise((resolve, reject) => {
    const out: Array<{ key: IDBValidKey; rec: any }> = [];
    const req = d.transaction(STORE, 'readonly').objectStore(STORE).openCursor();
    req.onsuccess = () => {
      const c = req.result;
      if (!c || out.length >= limit) return resolve(out);
      out.push({ key: c.key, rec: c.value });
      c.continue();
    };
    req.onerror = () => reject(req.error);
  });
}

export async function remove(keys: IDBValidKey[]): Promise<void> {
  await tx('readwrite', (s) => {
    for (const k of keys) s.delete(k);
  });
}
