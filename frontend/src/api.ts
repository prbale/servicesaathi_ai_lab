// Thin fetch wrapper. The token lives in memory + sessionStorage; the SERVER decides
// what each role may do. The UI only hides links for convenience.

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

let token: string | null = safeGet("ss_token");
let devMode = safeGet("ss_dev") === "1";
type TraceListener = (trace: any) => void;
const listeners = new Set<TraceListener>();

function safeGet(k: string): string | null {
  try {
    return sessionStorage.getItem(k);
  } catch {
    return null;
  }
}
function safeSet(k: string, v: string | null) {
  try {
    if (v === null) sessionStorage.removeItem(k);
    else sessionStorage.setItem(k, v);
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

export const session = {
  get token() {
    return token;
  },
  setToken(t: string | null) {
    token = t;
    safeSet("ss_token", t);
  },
  get devMode() {
    return devMode;
  },
  setDevMode(on: boolean) {
    devMode = on;
    safeSet("ss_dev", on ? "1" : "0");
  },
  onTrace(fn: TraceListener) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: any; headers?: Record<string, string>; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (devMode) headers["X-Developer-Mode"] = "1";
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/auth/login") {
      session.setToken(null);
      window.dispatchEvent(new Event("ss-signed-out"));
    }
    throw new ApiError(res.status, data?.detail ?? data);
  }
  if (data && data.trace) listeners.forEach((fn) => fn(data.trace));
  return data as T;
}

/** Raw call used by the Python & API Lab to show the exact request and response. */
export async function rawCall(method: string, path: string, body?: string) {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";
  const started = performance.now();
  const res = await fetch(path, { method, headers, body: body || undefined });
  const text = await res.text();
  return {
    status: res.status,
    ms: Math.round(performance.now() - started),
    headers: Object.fromEntries([...res.headers.entries()].filter(([k]) => k.startsWith("content"))),
    body: text,
  };
}

export function newIdempotencyKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.detail?.errors) return e.detail.errors.map((x: any) => `${x.field}: ${x.message}`).join("; ");
    return e.message;
  }
  return "Could not reach the server. Check that the backend is running.";
}
