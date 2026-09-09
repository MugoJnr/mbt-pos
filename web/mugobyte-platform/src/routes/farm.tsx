import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ensureAuthSession, POST } from "@/lib/api";

type FarmHandoffResponse = {
  ok?: boolean;
  handoff?: string;
  error?: string;
};

const ALLOWED_REDIRECTS = new Set([
  "https://farm.mugobyte.com/auth/portal",
  "mugobytefarm://auth-callback",
]);

export const Route = createFileRoute("/farm")({
  validateSearch: (search: Record<string, unknown>) => ({
    redirect: typeof search.redirect === "string" ? search.redirect : "",
    state: typeof search.state === "string" ? search.state : "",
  }),
  component: FarmHandoffPage,
  head: () => ({ meta: [{ title: "Open MBT FARM | MugoByte" }] }),
});

function FarmHandoffPage() {
  const { redirect, state } = Route.useSearch();
  const [message, setMessage] = useState("Checking your MugoByte Account…");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      if (!ALLOWED_REDIRECTS.has(redirect) || !state) {
        setMessage("This MBT FARM sign-in link is invalid. Return to Farm and try again.");
        return;
      }

      const authenticated = await ensureAuthSession();
      if (!authenticated) {
        const next = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`/login?redirect=${encodeURIComponent(next)}`);
        return;
      }

      setMessage("Opening MBT FARM…");
      const response = await POST<FarmHandoffResponse>("/cloud/farm/handoff", {
        redirect_uri: redirect,
      });
      if (cancelled) return;
      if (!response?.ok || !response.handoff) {
        setMessage("Farm sign-in could not be completed. Try again.");
        return;
      }

      const separator = redirect.includes("?") ? "&" : "?";
      window.location.replace(
        `${redirect}${separator}handoff=${encodeURIComponent(response.handoff)}&state=${encodeURIComponent(state)}`,
      );
    })().catch(() => {
      if (!cancelled) setMessage("Farm sign-in could not be completed. Try again.");
    });

    return () => {
      cancelled = true;
    };
  }, [redirect, state, retry]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <section className="w-full max-w-md rounded-2xl border bg-card p-8 text-center shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          MugoByte Account
        </p>
        <h1 className="mt-3 text-2xl font-semibold">MBT FARM</h1>
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          {message}
        </p>
        {message.includes("could not") ? (
          <button
            className="mt-6 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground"
            type="button"
            onClick={() => setRetry((value) => value + 1)}
          >
            Try again
          </button>
        ) : null}
      </section>
    </main>
  );
}
