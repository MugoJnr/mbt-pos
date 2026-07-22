import { createFileRoute, redirect } from "@tanstack/react-router";
import { ensureAuthSession, getToken } from "@/lib/api";

function hasAuthHash(): boolean {
  if (typeof window === "undefined") return false;
  const hash = window.location.hash || "";
  return (
    hash.includes("access_token=") ||
    hash.includes("type=signup") ||
    hash.includes("type=recovery") ||
    hash.includes("type=magiclink") ||
    hash.includes("type=email")
  );
}

export const Route = createFileRoute("/")({
  beforeLoad: async () => {
    // Supabase Site URL redirects often land on "/" with tokens in the hash.
    if (hasAuthHash()) {
      const hash = window.location.hash || "";
      window.location.replace(`/auth/callback${hash}`);
      return;
    }
    const ok = await ensureAuthSession();
    throw redirect({ to: ok || getToken() ? "/dashboard" : "/login" });
  },
});
