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
  login as apiLogin,
  setSession,
  type MbtUser,
} from "./api";

type AuthCtx = {
  token: string;
  user: MbtUser | null;
  isAuthed: boolean;
  login: (u: string, p: string) => Promise<string | null>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(getToken);
  const [user, setUser] = useState<MbtUser | null>(getUser);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    if (!res || res.error || !res.token || !res.user) {
      return res?.error || "Login failed";
    }
    setSession(res.token, res.user);
    setToken(res.token);
    setUser(res.user);
    return null;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setToken("");
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ token, user, isAuthed: Boolean(token), login, logout }),
    [token, user, login, logout],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** Show login screen when not authenticated; otherwise children. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { isAuthed, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  if (isAuthed) return <>{children}</>;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    const msg = await login(username.trim(), password);
    setBusy(false);
    if (msg) setErr(msg);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-app px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-2xl border border-border bg-card p-8 shadow-lg"
      >
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-xl bg-gold text-xl font-black text-[color:var(--gold-fg)]">
            MBT
          </div>
          <h1 className="text-xl font-extrabold text-text">Sign in</h1>
          <p className="mt-1 text-sm text-text2">MugoByte POS Web Dashboard</p>
        </div>
        {err ? (
          <div className="mb-4 rounded-md border border-err/40 bg-err/10 px-3 py-2 text-sm text-err">
            {err}
          </div>
        ) : null}
        <label className="mb-3 block text-sm font-semibold text-text2">
          Username
          <input
            className="mt-1 w-full rounded-lg border border-border2 bg-input px-3 py-2.5 text-text outline-none focus:border-gold"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="mb-5 block text-sm font-semibold text-text2">
          Password
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-border2 bg-input px-3 py-2.5 text-text outline-none focus:border-gold"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-xl bg-gold py-3 text-sm font-extrabold tracking-wide text-[color:var(--gold-fg)] hover:brightness-110 disabled:opacity-60"
        >
          {busy ? "Signing in…" : "SIGN IN"}
        </button>
      </form>
    </div>
  );
}
