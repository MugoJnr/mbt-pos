import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { setOrgId, setSession, type MbtUser, type Organization } from "@/lib/api";

export const Route = createFileRoute("/_auth/auth/callback")({
  head: () => ({ meta: [{ title: "Signing In | MugoByte" }] }),
  component: AuthCallbackPage,
});

type SessionResponse = {
  token?: string;
  user?: MbtUser;
  organizations?: Organization[];
  error?: string;
};

async function establishSessionFromHash(): Promise<{ ok: boolean; type: string; error?: string }> {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const query = new URLSearchParams(window.location.search);
  const error =
    hash.get("error_description") ||
    query.get("error_description") ||
    hash.get("error") ||
    query.get("error");
  if (error) return { ok: false, type: "", error };

  const accessToken = hash.get("access_token") || query.get("access_token") || "";
  const refreshToken = hash.get("refresh_token") || query.get("refresh_token") || "";
  const linkType = hash.get("type") || query.get("type") || "";

  // Recovery links should land on reset-password with tokens preserved.
  if (linkType === "recovery" && accessToken) {
    const next = `/reset-password#access_token=${encodeURIComponent(accessToken)}&refresh_token=${encodeURIComponent(refreshToken)}&type=recovery`;
    window.location.replace(next);
    return { ok: true, type: "recovery" };
  }

  if (!accessToken) {
    const hasHint =
      Boolean(query.get("code") || query.get("token_hash")) ||
      linkType === "signup" ||
      linkType === "email" ||
      linkType === "magiclink";
    return {
      ok: hasHint,
      type: linkType,
      error: hasHint ? undefined : "Missing session tokens in verification link.",
    };
  }

  const r = await fetch("/api/cloud/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({
      access_token: accessToken,
      refresh_token: refreshToken,
    }),
  });
  const data = (await r.json().catch(() => ({}))) as SessionResponse;
  if (!r.ok || !data.token || !data.user) {
    return { ok: false, type: linkType, error: data.error || "Could not create session from link." };
  }

  setSession(data.token, data.user, "supabase");
  const primary = (data.organizations || []).find((o) => o.is_primary) || data.organizations?.[0];
  if (primary?.id) setOrgId(primary.id);
  window.history.replaceState(null, "", "/auth/callback");
  return { ok: true, type: linkType || "signup" };
}

function AuthCallbackPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean | null>(null);
  const [message, setMessage] = useState("Confirming your email…");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await establishSessionFromHash();
        if (cancelled) return;
        if (result.type === "recovery") return;
        setVerified(result.ok);
        if (result.ok) {
          setMessage("Email verified. Opening your workspace…");
          setTimeout(() => navigate({ to: "/dashboard" }), 600);
        } else {
          setMessage(result.error || "The link is invalid or expired.");
        }
      } catch (e) {
        if (!cancelled) {
          setVerified(false);
          setMessage(e instanceof Error ? e.message : "Verification failed.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  return (
    <div className="animate-fade-in text-center">
      {verified === null ? (
        <Loader2 className="mx-auto h-10 w-10 animate-spin text-primary" />
      ) : verified ? (
        <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
      ) : (
        <XCircle className="mx-auto h-10 w-10 text-destructive" />
      )}
      <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight">
        {verified === false ? "Verification link failed" : verified ? "Signed in" : "Confirming…"}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      {verified === false && (
        <Button asChild className="mt-6">
          <Link to="/verify-email">Resend verification email</Link>
        </Button>
      )}
      {verified === true && (
        <Button asChild className="mt-6" variant="outline">
          <Link to="/dashboard">Open workspace</Link>
        </Button>
      )}
    </div>
  );
}
