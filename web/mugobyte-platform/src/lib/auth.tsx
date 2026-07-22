import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearSession,
  ensureAuthSession,
  getToken,
  getUser,
  getOrgId,
  login as apiLogin,
  registerCloud,
  bootstrapCloud,
  logoutCloud,
  setSession,
  setOrgId,
  syncSessionUser,
  isPlatformAdmin,
  type MbtUser,
  type Organization,
} from "./api";

type AuthCtx = {
  token: string;
  user: MbtUser | null;
  orgId: string;
  isAuthed: boolean;
  authReady: boolean;
  login: (u: string, p: string, remember?: boolean) => Promise<string | null>;
  register: (data: {
    email: string;
    password: string;
    full_name?: string;
    business_name?: string;
  }) => Promise<string | null>;
  logout: () => void;
  setActiveOrg: (id: string) => void;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(getToken);
  const [user, setUser] = useState<MbtUser | null>(getUser);
  const [orgId, setOrgIdState] = useState(getOrgId);
  const [authReady, setAuthReady] = useState(() => Boolean(getToken()));

  // Restore from HttpOnly refresh cookie when access token is missing/expired.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const restored = await ensureAuthSession();
      if (cancelled) return;
      if (restored) {
        setToken(getToken());
        setUser(getUser());
        const live = await syncSessionUser();
        if (!cancelled && live) setUser(live);
      } else if (getToken()) {
        // Token present but refresh not needed — still sync role claims.
        const live = await syncSessionUser();
        if (!cancelled && live) setUser(live);
      }
      if (!cancelled) setAuthReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string, remember = true) => {
    const res = await apiLogin(username, password);
    if (!res || res.error || !res.token || !res.user) {
      return res?.error || "Login failed";
    }
    // If JWT already has platform_admin but payload role lagged, prefer JWT.
    const nextUser = isPlatformAdmin(res.user)
      ? { ...res.user, role: "platform_admin" }
      : res.user;
    setSession(res.token, nextUser, res.provider || "local", remember);
    setToken(res.token);
    setUser(nextUser);
    setAuthReady(true);
    let orgs = res.organizations || [];
    if ((!orgs.length) && (res.provider === "supabase" || username.includes("@"))) {
      try {
        const boot = await bootstrapCloud();
        if (boot?.organizations?.length) orgs = boot.organizations;
      } catch {
        /* ignore — never wipe a successful login if bootstrap fails */
      }
    }
    const primary = orgs.find((o) => o.is_primary) || orgs[0];
    if (primary?.id) {
      setOrgId(primary.id);
      setOrgIdState(primary.id);
    }
    return null;
  }, []);

  const register = useCallback(
    async (data: { email: string; password: string; full_name?: string; business_name?: string }) => {
      const res = await registerCloud(data);
      if (res?.verification_required) {
        return "VERIFY_EMAIL";
      }
      if (!res || res.error || !res.token || !res.user) {
        return res?.error || "Registration failed";
      }
      setSession(res.token, res.user, "supabase", true);
      setToken(res.token);
      setUser(res.user);
      setAuthReady(true);
      const primary = (res.organizations || []).find((o) => o.is_primary) || res.organizations?.[0];
      if (primary?.id) {
        setOrgId(primary.id);
        setOrgIdState(primary.id);
      }
      return null;
    },
    [],
  );

  const logout = useCallback(() => {
    void logoutCloud();
    clearSession();
    setToken("");
    setUser(null);
    setOrgIdState("");
    setAuthReady(true);
  }, []);

  const setActiveOrg = useCallback((id: string) => {
    setOrgId(id);
    setOrgIdState(id);
  }, []);

  const value = useMemo(
    () => ({
      token,
      user,
      orgId,
      isAuthed: Boolean(token),
      authReady,
      login,
      register,
      logout,
      setActiveOrg,
    }),
    [token, user, orgId, authReady, login, register, logout, setActiveOrg],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function requireAuth() {
  if (!getToken()) {
    throw new Error("REDIRECT_LOGIN");
  }
}

export type { Organization };
