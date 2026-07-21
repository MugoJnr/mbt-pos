/** MugoByte Platform API client — shared with MBT POS desktop/web backend */

const TOKEN_KEY = "mbt_token";
const USER_KEY = "mbt_user";
const ORG_KEY = "mbt_org";
const PROVIDER_KEY = "mbt_auth_provider";

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
  const token = sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
  if (token && !sessionStorage.getItem(TOKEN_KEY)) {
    sessionStorage.setItem(TOKEN_KEY, token);
    localStorage.removeItem(TOKEN_KEY);
  }
  return token;
}

export function getUser(): MbtUser | null {
  try {
    const raw = sessionStorage.getItem(USER_KEY) || localStorage.getItem(USER_KEY) || "null";
    if (raw !== "null" && !sessionStorage.getItem(USER_KEY)) {
      sessionStorage.setItem(USER_KEY, raw);
      localStorage.removeItem(USER_KEY);
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function isPlatformAdmin(user: MbtUser | null = getUser()): boolean {
  // Shop POS roles like "admin" must never open the platform console.
  return String(user?.role || "").toLowerCase() === "platform_admin";
}

export function getOrgId(): string {
  return localStorage.getItem(ORG_KEY) || "";
}

export function setOrgId(id: string) {
  if (id) localStorage.setItem(ORG_KEY, id);
  else localStorage.removeItem(ORG_KEY);
}

export function setSession(token: string, user: MbtUser, provider = "local") {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  sessionStorage.setItem(PROVIDER_KEY, provider);
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(PROVIDER_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ORG_KEY);
  localStorage.removeItem(PROVIDER_KEY);
}

export async function api<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  noAuth = false,
  allowRefresh = true,
): Promise<T | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (!noAuth && token) headers.Authorization = `Bearer ${token}`;
  const opts: RequestInit = { method, headers, credentials: "same-origin" };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch("/api" + path, opts);
  const data = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (r.status === 401 && !noAuth) {
    if (allowRefresh && !path.startsWith("/cloud/auth/")) {
      const refreshed = await refreshCloudSession();
      if (refreshed) return api<T>(method, path, body, noAuth, false);
    }
    clearSession();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
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
  const data = (await r.json().catch(() => ({}))) as { token?: string };
  if (!data.token) return false;
  sessionStorage.setItem(TOKEN_KEY, data.token);
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
  return GET<{ licenses: CloudLicense[]; org_id?: string; error?: string }>(
    "/cloud/licenses",
    { org_id: orgId || getOrgId() || undefined },
  );
}

export function createCloudLicense(plan: string, notes = "", orgId?: string) {
  return POST<{ ok?: boolean; license?: CloudLicense; error?: string }>("/cloud/licenses", {
    plan,
    notes,
    org_id: orgId || getOrgId() || undefined,
  });
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
  return POST<{ ok?: boolean; commands_issued?: number; error?: string }>(
    `/cloud/licenses/${licenseId}/suspend`,
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
    { org_id: orgId || getOrgId() || undefined, limit },
  );
}

export function bootstrapCloud() {
  return POST<{ ok?: boolean; organizations?: Organization[]; error?: string }>("/cloud/bootstrap", {});
}

export function isAuthed(): boolean {
  return Boolean(getToken());
}
