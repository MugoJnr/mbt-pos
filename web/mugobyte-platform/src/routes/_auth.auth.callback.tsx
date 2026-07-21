import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_auth/auth/callback")({
  head: () => ({ meta: [{ title: "Signing In | MugoByte" }] }),
  component: AuthCallbackPage,
});

function AuthCallbackPage() {
  const [verified, setVerified] = useState<boolean | null>(null);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);
    const error = hash.get("error_description") || query.get("error_description") || hash.get("error") || query.get("error");
    const success =
      !error &&
      Boolean(
        hash.get("access_token") ||
          query.get("code") ||
          query.get("token_hash") ||
          query.get("type") === "signup" ||
          query.get("type") === "email" ||
          hash.get("type") === "signup" ||
          hash.get("type") === "recovery",
      );
    setVerified(success);
    window.history.replaceState(null, "", "/auth/callback");
  }, []);

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
        {verified === false ? "Verification link failed" : "Email verified"}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {verified === false
          ? "The link is invalid or expired. Register again or request a fresh verification email."
          : "Your MugoByte account is ready. Sign in to create or select your business."}
      </p>
      <Button asChild className="mt-6">
        <Link to={verified === false ? "/register" : "/login"}>
          {verified === false ? "Back to registration" : "Continue to sign in"}
        </Link>
      </Button>
    </div>
  );
}
