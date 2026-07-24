/** MugoByte Platform API client — shared with MBT POS desktop/web backend */

const TOKEN_KEY = "mbt_token";
const USER_KEY = "mbt_user";
const ORG_KEY = "mbt_org";
const PROVIDER_KEY = "mbt_auth_provider";
const REMEMBER_KEY = "mbt_remember";

/** Auth endpoints that must never trigger a recursive refresh attempt. */
const AUTH_NO_REFRESH_PREFIXES = [
  "/cloud/auth/login",
  "/cloud/auth/register",
  "/cloud/auth/refresh",
  "/cloud/auth/logout",
  "/cloud/auth/forgot-password",
  "/cloud/auth/update-password",
  "/cloud/auth/resend-verification",
  "/cloud/auth/session",
];

let authBootstrapPromise: Promise<boolean> | null = null;

function shouldAttemptRefresh(path: string): boolean {
  return !AUTH_NO_REFRESH_PREFIXES.some((prefix) => path.startsWith(prefix));
}

function prefersRemember(): boolean {
  return localStorage.getItem(REMEMBER_KEY) === "1";
}

export type MbtUser = {
  id?: number | string;
  username?: string;
  full_name?: string;
  role?: string;
  tab_permissions?: string[];
  email?: string;
  [key: string]: unknown;
};

export type Organization = {
  id: string;
  name: string;
  slug?: string;
  role?: string;
  is_primary?: boolean;
  plan?: string;
  status?: string;
};

export function getToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
}

export function getUser(): MbtUser | null {
  try {
    const raw = sessionStorage.getItem(USER_KEY) || localStorage.getItem(USER_KEY) || "null";
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function getAuthProvider(): string {
  return sessionStorage.getItem(PROVIDER_KEY) || localStorage.getItem(PROVIDER_KEY) || "supabase";
}

function platformRoleFromJwt(token = getToken()): string {
  if (!token || token.split(".").length < 2) return "";
  try {
    const raw = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = raw + "=".repeat((4 - (raw.length % 4)) % 4);
    const payload = JSON.parse(atob(padded)) as {
      app_metadata?: { platform_role?: string };
    };
    return String(payload?.app_metadata?.platform_role || "");
  } catch {
    return "";
  }
}

export function isPlatformAdmin(user: MbtUser | null = getUser()): boolean {
  // Shop POS roles like "admin" must never open the platform console.
  // Prefer stored user, but also trust JWT app_metadata after role elevation
  // so a stale mbt_user session cannot hide Platform Admin.
  const fromUser = String(user?.role || "").toLowerCase();
  if (fromUser === "platform_admin") return true;
  return platformRoleFromJwt().toLowerCase() === "platform_admin";
}

/** Refresh stored user role from live Auth claims (after platform_admin elevation). */
export async function syncSessionUser(): Promise<MbtUser | null> {
  const token = getToken();
  if (!token) return null;
  // Allow one refresh on 401 — do not wipe a still-valid refresh cookie.
  const data = await api<{ user?: MbtUser; error?: string }>(
    "GET",
    "/cloud/auth/me",
    undefined,
    false,
    true,
    false,
  );
  if (!data?.user) {
    if (!getToken()) return null;
    return getUser();
  }
  setSession(getToken(), data.user, getAuthProvider());
  return data.user;
}

export function getOrgId(): string {
  return localStorage.getItem(ORG_KEY) || "";
}

export function setOrgId(id: string) {
  if (id) localStorage.setItem(ORG_KEY, id);
  else localStorage.removeItem(ORG_KEY);
}

export function setSession(
  token: string,
  user: MbtUser,
  provider = "local",
  remember?: boolean,
) {
  if (remember !== undefined) {
    localStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
  }
  const persist = remember ?? prefersRemember();
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  sessionStorage.setItem(PROVIDER_KEY, provider);
  if (persist) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    localStorage.setItem(PROVIDER_KEY, provider);
  } else {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(PROVIDER_KEY);
  }
  authBootstrapPromise = Promise.resolve(true);
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(PROVIDER_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ORG_KEY);
  localStorage.removeItem(PROVIDER_KEY);
  authBootstrapPromise = null;
}

/**
 * Restore access token before route guards run.
 * Uses existing storage first; otherwise exchanges the HttpOnly refresh cookie.
 */
export function ensureAuthSession(): Promise<boolean> {
  if (getToken()) return Promise.resolve(true);
  if (!authBootstrapPromise) {
    authBootstrapPromise = refreshCloudSession().then((ok) => {
      if (!ok && !getToken()) {
        // Allow a later login / navigation to try again.
        authBootstrapPromise = null;
      }
      return ok || Boolean(getToken());
    });
  }
  return authBootstrapPromise;
}

export async function api<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  noAuth = false,
  allowRefresh = true,
  clearOnUnauthorized = true,
): Promise<T | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (!noAuth && token) headers.Authorization = `Bearer ${token}`;
  const opts: RequestInit = { method, headers, credentials: "same-origin" };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  const data = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (r.status === 401 && !noAuth) {
    if (allowRefresh && shouldAttemptRefresh(path)) {
      const refreshed = await refreshCloudSession();
      if (refreshed) return api<T>(method, path, body, noAuth, false, clearOnUnauthorized);
    }
    if (clearOnUnauthorized) {
      clearSession();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return null;
  }
  return data;
}

export const GET = <T = unknown>(path: string, q?: Record<string, string | undefined>) => {
  const params = new URLSearchParams();
  if (q) {
    for (const [k, v] of Object.entries(q)) {
      if (v != null && v !== "") params.set(k, v);
    }
  }
  const qs = params.toString();
  return api<T>("GET", path + (qs ? "?" + qs : ""));
};

export const POST = <T = unknown>(path: string, body?: unknown) => api<T>("POST", path, body);
export const PUT = <T = unknown>(path: string, body?: unknown) => api<T>("PUT", path, body);

/** Download an authenticated analytics export without loading the full result into the browser. */
export async function downloadAnalyticsExport(
  query: Record<string, string | undefined>,
  allowRefresh = true,
): Promise<void> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value != null && value !== "") params.set(key, value);
  }
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/cloud/analytics/export?${params.toString()}`, {
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && allowRefresh && (await refreshCloudSession())) {
    return downloadAnalyticsExport(query, false);
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(payload.error || `Export failed (${response.status})`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const filename =
    disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i)?.[1] ||
    `mbt-${query.report || "analytics"}-${query.start || "export"}.${query.format || "csv"}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = decodeURIComponent(filename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

type LoginResult = {
  token?: string;
  user?: MbtUser;
  error?: string;
  provider?: string;
  organizations?: Organization[];
  refresh_token?: string;
  verification_required?: boolean;
  message?: string;
};

/** Portal login: cloud email only. Local POS shop accounts cannot access Portal. */
export async function login(username: string, password: string): Promise<LoginResult | null> {
  const email = username.trim();
  if (!email.includes("@")) {
    return {
      error: "Use your Portal email address to sign in. Local POS usernames are not accepted here.",
    };
  }
  const cloud = await api<LoginResult>(
    "POST",
    "/cloud/auth/login",
    { email, password },
    true,
  );
  if (cloud?.token && cloud?.user) {
    return { ...cloud, provider: "supabase" };
  }
  return cloud;
}

export async function registerCloud(payload: {
  email: string;
  password: string;
  full_name?: string;
  business_name?: string;
}): Promise<LoginResult | null> {
  return api<LoginResult>("POST", "/cloud/auth/register", payload, true);
}

export async function forgotPassword(email: string) {
  return api<{ ok?: boolean; message?: string }>("POST", "/cloud/auth/forgot-password", { email }, true);
}

export async function resendVerification(email: string) {
  return api<{ ok?: boolean; message?: string; error?: string }>(
    "POST",
    "/cloud/auth/resend-verification",
    { email },
    true,
  );
}

export async function refreshCloudSession(): Promise<boolean> {
  const r = await fetch("/api/cloud/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
  });
  if (!r.ok) return false;
  const data = (await r.json().catch(() => ({}))) as {
    token?: string;
    user?: MbtUser;
  };
  if (!data.token) return false;
  const provider = getAuthProvider();
  const existing = getUser();
  if (data.user) {
    setSession(data.token, data.user, provider);
  } else if (existing) {
    setSession(data.token, existing, provider);
  } else {
    // Token-only restore (rare) — keep storage coherent for guards.
    sessionStorage.setItem(TOKEN_KEY, data.token);
    if (prefersRemember()) localStorage.setItem(TOKEN_KEY, data.token);
  }
  return true;
}

export async function logoutCloud(): Promise<void> {
  await fetch("/api/cloud/auth/logout", {
    method: "POST",
    credentials: "same-origin",
  }).catch(() => undefined);
}

export async function updatePassword(recoveryToken: string, password: string) {
  return api<{ ok?: boolean; error?: string }>(
    "POST",
    "/cloud/auth/update-password",
    { recovery_token: recoveryToken, password },
    true,
  );
}

export type CloudLicense = {
  id?: string;
  org_id?: string;
  license_key?: string;
  plan?: string;
  status?: string;
  max_devices?: number;
  activated_devices?: number;
  expires_at?: string;
  activated_at?: string;
  notes?: string;
  created_at?: string;
  product_id?: string | null;
  assigned_email?: string | null;
  assigned_user_id?: string | null;
  reserved_device_id?: string | null;
  claim_status?: string | null;
  claimed_at?: string | null;
  assigned_at?: string | null;
};

export type CloudDevice = {
  id?: string;
  org_id?: string;
  business_id?: string;
  device_id?: string;
  hostname?: string;
  computer_name?: string;
  platform?: string;
  mbt_version?: string;
  os_info?: string;
  hardware_fingerprint?: string;
  last_seen_at?: string;
  last_sync_at?: string;
  sync_status?: string;
  approval_status?: string;
  is_active?: boolean;
  approved_at?: string;
  rejected_at?: string;
  deactivated_at?: string;
};

export function listCloudLicenses(orgId?: string) {
  const q: Record<string, string | undefined> = {
    org_id: orgId || getOrgId() || undefined,
  };
  // Platform admin console lists every org's licenses.
  if (isPlatformAdmin()) q.all = "1";
  return GET<{ licenses: CloudLicense[]; org_id?: string; scope?: string; error?: string }>(
    "/cloud/licenses",
    q,
  );
}

export function createCloudLicense(
  plan: string,
  notes = "",
  orgId?: string,
  opts?: { assigned_email?: string; reserved_device_id?: string; product_id?: string },
) {
  return POST<{ ok?: boolean; license?: CloudLicense; error?: string }>("/cloud/licenses", {
    plan,
    notes,
    org_id: orgId || getOrgId() || undefined,
    assigned_email: opts?.assigned_email || undefined,
    reserved_device_id: opts?.reserved_device_id || undefined,
    product_id: opts?.product_id || undefined,
  });
}

export function assignCloudLicense(
  licenseId: string,
  opts: {
    assigned_email?: string;
    reserved_device_id?: string;
    clear?: boolean;
  },
) {
  return POST<{ ok?: boolean; message?: string; license?: CloudLicense; error?: string }>(
    `/cloud/licenses/${licenseId}/assign`,
    {
      assigned_email: opts.assigned_email || undefined,
      reserved_device_id: opts.reserved_device_id || undefined,
      clear: opts.clear || undefined,
    },
  );
}

export function activateCloudLicense(licenseKey: string, deviceId?: string, orgId?: string) {
  return POST<{ ok?: boolean; message?: string; license?: CloudLicense; error?: string }>(
    "/cloud/licenses/activate",
    {
      license_key: licenseKey,
      device_id: deviceId,
      org_id: orgId || getOrgId() || undefined,
    },
  );
}

export function revokeCloudLicense(licenseId: string) {
  return POST<{ ok?: boolean; commands_issued?: number; error?: string }>(
    `/cloud/licenses/${licenseId}/revoke`,
    {},
  );
}

export function suspendCloudLicense(licenseId: string) {
  return POST<{ ok?: boolean; commands_issued?: number; license?: CloudLicense; error?: string }>(
    `/cloud/licenses/${licenseId}/suspend`,
    {},
  );
}

export function unsuspendCloudLicense(licenseId: string) {
  return POST<{ ok?: boolean; commands_issued?: number; license?: CloudLicense; error?: string }>(
    `/cloud/licenses/${licenseId}/unsuspend`,
    {},
  );
}

export function renewCloudLicense(licenseId: string, days = 30) {
  return POST<{ ok?: boolean; commands_issued?: number; error?: string }>(
    `/cloud/licenses/${licenseId}/renew`,
    { days },
  );
}

export function forceValidateCloudLicense(licenseId: string) {
  return POST<{ ok?: boolean; commands_issued?: number; error?: string }>(
    `/cloud/licenses/${licenseId}/force-validate`,
    {},
  );
}

export function transferCloudLicense(licenseId: string, oldDeviceId: string, newDeviceId: string) {
  return POST<{ ok?: boolean; message?: string; error?: string }>(
    `/cloud/licenses/${licenseId}/transfer`,
    { old_device_id: oldDeviceId, new_device_id: newDeviceId },
  );
}

export function licenseHistory(licenseId: string) {
  return GET<{ history: Array<Record<string, unknown>>; error?: string }>(
    `/cloud/licenses/${licenseId}/history`,
  );
}

export function issueCloudCommand(deviceId: string, command: string, params?: Record<string, unknown>, orgId?: string) {
  return POST<{ ok?: boolean; command?: unknown; error?: string }>("/cloud/commands", {
    device_id: deviceId,
    command,
    params: params || {},
    org_id: orgId || getOrgId() || undefined,
  });
}

export function listSecurityEvents(orgId?: string) {
  return GET<{
    audit_logs: Array<Record<string, unknown>>;
    license_history: Array<Record<string, unknown>>;
    error?: string;
  }>("/cloud/security-events", { org_id: orgId || getOrgId() || undefined });
}

export function listCloudDevices(orgId?: string) {
  return GET<{ devices: CloudDevice[]; org_id?: string; error?: string }>(
    "/cloud/devices",
    { org_id: orgId || getOrgId() || undefined },
  );
}

export function approveCloudDevice(deviceId: string, orgId?: string, reason = "") {
  return POST<{ ok?: boolean; device?: CloudDevice; error?: string }>(
    `/cloud/devices/${encodeURIComponent(deviceId)}/approve`,
    { org_id: orgId || getOrgId() || undefined, reason },
  );
}

export function rejectCloudDevice(deviceId: string, orgId?: string, reason = "") {
  return POST<{ ok?: boolean; device?: CloudDevice; error?: string }>(
    `/cloud/devices/${encodeURIComponent(deviceId)}/reject`,
    { org_id: orgId || getOrgId() || undefined, reason },
  );
}

export function renameCloudDevice(deviceId: string, computerName: string, orgId?: string) {
  return POST<{ ok?: boolean; device?: CloudDevice; error?: string }>(
    `/cloud/devices/${encodeURIComponent(deviceId)}/rename`,
    { org_id: orgId || getOrgId() || undefined, computer_name: computerName },
  );
}

export function deactivateCloudDevice(deviceId: string, orgId?: string, reason = "") {
  return POST<{ ok?: boolean; device?: CloudDevice; error?: string }>(
    `/cloud/devices/${encodeURIComponent(deviceId)}/deactivate`,
    { org_id: orgId || getOrgId() || undefined, reason },
  );
}

export function listDeviceEvents(orgId?: string, limit = 50) {
  return GET<{ events: Array<Record<string, unknown>>; org_id?: string; error?: string }>(
    "/cloud/devices/events",
    { org_id: orgId || getOrgId() || undefined, limit: String(limit) },
  );
}

export function bootstrapCloud() {
  // Never wipe a fresh login if bootstrap hiccups (401/network).
  return api<{ ok?: boolean; organizations?: Organization[]; error?: string }>(
    "POST",
    "/cloud/bootstrap",
    {},
    false,
    true,
    false,
  );
}

export function isAuthed(): boolean {
  return Boolean(getToken());
}
