import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Admin = { username?: string; full_name?: string; active?: boolean };
type Context = {
  explanation?: string;
  shop_name?: string;
  shop_id?: string;
  device_id?: string;
  licence_state?: string;
  superadmins?: Admin[];
  error?: string;
  portal_changes_password?: boolean;
};

export function DeveloperRecovery({ onBack }: { onBack: () => void }) {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [ok, setOk] = useState(false);

  useEffect(() => {
    void api<Context>("GET", "/auth/recovery/context", undefined, true).then((res) => {
      setCtx(res || { error: "This computer could not show its shop identity." });
    });
  }, []);

  const admins = (ctx?.superadmins || []).filter((row) => row.active !== false && row.username);
  const adminText = admins.length
    ? admins.map((row) => `${row.full_name || row.username} (${row.username})`).join(", ")
    : "No active Super Admin";

  return (
    <form
      className="relative w-full max-w-md rounded-2xl border border-border bg-card/95 p-8 shadow-elevated"
      onSubmit={async (event) => {
        event.preventDefault();
        setMessage("");
        setOk(false);
        const entered = token;
        const res = await api<{ success?: boolean; error?: string; username?: string }>(
          "POST",
          "/auth/recovery/redeem",
          { token: entered, new_password: password, confirm_password: confirm },
          true,
        );
        if (res?.success) {
          setToken("");
          setPassword("");
          setConfirm("");
          setOk(true);
          setMessage(
            `Password updated for ${res.username || "the Super Admin"}. Sign in with the new password. The old password was not shown.`,
          );
          return;
        }
        setMessage(res?.error || "Recovery failed.");
      }}
    >
      <div className="mb-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-gold">
        MBT POS · Password Recovery
      </div>
      <h1 className="text-xl font-extrabold text-text">Developer emergency recovery</h1>
      <p className="mt-2 text-sm text-text2">
        {ctx?.explanation ||
          "A MugoByte developer issues a one-time code. The portal does not change this password. This dashboard checks the code on this shop computer, with no network required."}
      </p>
      <dl className="mt-4 space-y-1 rounded-xl border border-border bg-input/40 p-3 text-sm text-text">
        <div><dt className="inline text-text2">Shop: </dt><dd className="inline">{ctx?.shop_name || "—"}</dd></div>
        <div><dt className="inline text-text2">Shop id: </dt><dd className="inline break-all">{ctx?.shop_id || "—"}</dd></div>
        <div><dt className="inline text-text2">Device: </dt><dd className="inline break-all">{ctx?.device_id || "—"}</dd></div>
        <div><dt className="inline text-text2">Licence: </dt><dd className="inline">{ctx?.licence_state || "—"}</dd></div>
        <div><dt className="inline text-text2">Super Admin: </dt><dd className="inline">{adminText}</dd></div>
      </dl>
      {ctx?.error ? <p className="mt-3 text-sm text-err">{ctx.error}</p> : null}
      <label className="mt-4 block text-sm font-semibold text-text2">
        Recovery code
        <input
          aria-label="Recovery code"
          className="mt-1.5 w-full min-h-12 rounded-lg border border-border2 bg-input px-3 py-2 text-center font-mono text-lg uppercase tracking-[0.22em] text-text outline-none focus:border-gold"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="K7NP-4RWM-9QHD"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          maxLength={20}
          required
        />
        <span className="mt-1 block text-xs font-normal text-text2">12 characters. Dashes and spaces are optional.</span>
      </label>
      <label className="mt-3 block text-sm font-semibold text-text2">
        New Super Admin password
        <input
          type="password"
          aria-label="New Super Admin password"
          className="mt-1.5 w-full min-h-11 rounded-lg border border-border2 bg-input px-3 py-2.5 text-text outline-none focus:border-gold"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          required
        />
      </label>
      <label className="mt-3 block text-sm font-semibold text-text2">
        Confirm new password
        <input
          type="password"
          aria-label="Confirm new password"
          className="mt-1.5 w-full min-h-11 rounded-lg border border-border2 bg-input px-3 py-2.5 text-text outline-none focus:border-gold"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          autoComplete="new-password"
          required
        />
      </label>
      {message ? (
        <p className={`mt-3 text-sm ${ok ? "text-text" : "text-err"}`}>{message}</p>
      ) : null}
      <button
        type="submit"
        className="mt-4 w-full min-h-11 rounded-xl bg-gold py-3 text-sm font-extrabold text-[color:var(--gold-fg)]"
      >
        Set Super Admin password
      </button>
      <button type="button" onClick={onBack} className="mt-3 w-full text-sm font-semibold text-text2 hover:text-gold">
        Back to sign in
      </button>
    </form>
  );
}
