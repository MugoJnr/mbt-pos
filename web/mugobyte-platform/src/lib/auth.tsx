import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearSession,
  getToken,
  getUser,
  getOrgId,
  login as apiLogin,
  registerCloud,
  bootstrapCloud,
  logoutCloud,
  setSession,
  setOrgId,
  type MbtUser,
  type Organization,
} from "./api";

type AuthCtx = {
  token: string;
  user: MbtUser | null;
  orgId: string;
  isAuthed: boolean;
  login: (u: string, p: string) => Promise<string | null>;
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

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    if (!res || res.error || !res.token || !res.user) {
      return res?.error || "Login failed";
    }
    setSession(res.token, res.user, res.provider || "local");
    setToken(res.token);
    setUser(res.user);
    let orgs = res.organizations || [];
    if ((!orgs.length) && (res.provider === "supabase" || username.includes("@"))) {
      try {
        const boot = await bootstrapCloud();
        if (boot?.organizations?.length) orgs = boot.organizations;
      } catch {
        /* ignore */
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
      setSession(res.token, res.user, "supabase");
      setToken(res.token);
      setUser(res.user);
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
      login,
      register,
      logout,
      setActiveOrg,
    }),
    [token, user, orgId, login, register, logout, setActiveOrg],
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
