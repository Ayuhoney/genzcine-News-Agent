/**
 * Device identifier — triple-persisted: localStorage + sessionStorage-backed cookie + IndexedDB.
 * All three must be cleared to get a new ID. Clearing one layer just re-reads from another.
 * The server also tracks by IP, so localStorage-only reset still hits the IP gate.
 */

const LS_KEY = 'gzc_did';
const CK_KEY = 'gzc_did';
const IDB_KEY = 'device_id';
const IDB_STORE = 'meta';
const IDB_NAME = 'gzc_db';

function makeUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ── Cookie helpers ────────────────────────────────────────────────────────────

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return match ? match[1] : null;
}

function setCookie(name: string, value: string) {
  if (typeof document === 'undefined') return;
  // 1 year, SameSite=Lax (no HttpOnly so JS can read, but survives localStorage clear)
  const expires = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `${name}=${value}; expires=${expires}; path=/; SameSite=Lax`;
}

// ── IndexedDB helpers ────────────────────────────────────────────────────────

function idbGet(): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(IDB_NAME, 1);
      req.onupgradeneeded = (e) => {
        (e.target as IDBOpenDBRequest).result.createObjectStore(IDB_STORE);
      };
      req.onsuccess = (e) => {
        const db = (e.target as IDBOpenDBRequest).result;
        const tx = db.transaction(IDB_STORE, 'readonly');
        const getReq = tx.objectStore(IDB_STORE).get(IDB_KEY);
        getReq.onsuccess = () => resolve((getReq.result as string) ?? null);
        getReq.onerror = () => resolve(null);
      };
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

function idbSet(value: string): void {
  try {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = (e) => {
      (e.target as IDBOpenDBRequest).result.createObjectStore(IDB_STORE);
    };
    req.onsuccess = (e) => {
      const db = (e.target as IDBOpenDBRequest).result;
      db.transaction(IDB_STORE, 'readwrite').objectStore(IDB_STORE).put(value, IDB_KEY);
    };
  } catch {
    // IDB unavailable — silently ignore
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

let _cached: string | null = null;

export function getDeviceId(): string {
  if (typeof window === 'undefined') return '';
  if (_cached) return _cached;

  // Read from all three stores — use whichever is populated
  const fromLS = localStorage.getItem(LS_KEY);
  const fromCK = getCookie(CK_KEY);

  const id = fromLS ?? fromCK ?? makeUUID();

  // Write to all three stores (sync ones immediately, IDB async)
  if (!fromLS) localStorage.setItem(LS_KEY, id);
  if (!fromCK) setCookie(CK_KEY, id);
  idbSet(id); // always ensure IDB is in sync

  _cached = id;
  return id;
}

/**
 * Call on app init to also read from IndexedDB and sync all stores.
 * If IDB has a different (older) ID than LS+cookie, IDB wins (harder to clear).
 */
export async function initDeviceId(): Promise<string> {
  if (typeof window === 'undefined') return '';

  const fromLS = localStorage.getItem(LS_KEY);
  const fromCK = getCookie(CK_KEY);
  const fromIDB = await idbGet();

  // Prefer IDB > cookie > LS > new
  const id = fromIDB ?? fromCK ?? fromLS ?? makeUUID();

  // Sync all stores to the winning value
  localStorage.setItem(LS_KEY, id);
  setCookie(CK_KEY, id);
  if (!fromIDB) idbSet(id);

  _cached = id;
  return id;
}
