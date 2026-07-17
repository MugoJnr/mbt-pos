/** MBT POS web API client — same contract as legacy dashboard.html */

const TOKEN_KEY = "mbt_token";
const USER_KEY = "mbt_user";

export type MbtUser = {
  id?: number;
  username?: string;
  full_name?: string;
  role?: string;
  tab_permissions?: string[];
  [key: string]: unknown;
};

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function getUser(): MbtUser | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}

export function setSession(token: string, user: MbtUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function api<T = any>(
  method: string,
  path: string,
  body?: unknown,
  noAuth = false,
): Promise<T | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (!noAuth && token) headers.Authorization = `Bearer ${token}`;
  const opts: RequestInit = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  const data = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (r.status === 401 && !noAuth) {
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    return null;
  }
  return data;
}

export const GET = <T = any>(path: string, q?: Record<string, string>) =>
  api<T>("GET", path + (q ? "?" + new URLSearchParams(q) : ""));

export const POST = <T = any>(path: string, body?: unknown) => api<T>("POST", path, body);
export const PUT = <T = any>(path: string, body?: unknown) => api<T>("PUT", path, body);
export const DEL = <T = any>(path: string) => api<T>("DELETE", path);

export async function login(username: string, password: string) {
  return api<{ token?: string; user?: MbtUser; error?: string }>(
    "POST",
    "/auth/login",
    { username, password },
    true,
  );
}
