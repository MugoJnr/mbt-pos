import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updatePassword } from "@/lib/api";

export const Route = createFileRoute("/_auth/reset-password")({
  head: () => ({ meta: [{ title: "Reset Password | MugoByte" }] }),
  component: ResetPage,
});

function ResetPage() {
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);
    const linkError =
      hash.get("error_description") ||
      query.get("error_description") ||
      hash.get("error") ||
      query.get("error");
    if (linkError) {
      toast.error("Reset link invalid", {
        description: decodeURIComponent(linkError.replace(/\+/g, " ")),
      });
      window.history.replaceState(null, "", "/reset-password");
      setReady(true);
      return;
    }
    const access =
      hash.get("access_token") ||
      query.get("access_token") ||
      query.get("token") ||
      "";
    const type = hash.get("type") || query.get("type") || "";
    if (access) {
      setToken(access);
      window.history.replaceState(null, "", "/reset-password");
    }
    if (type && type !== "recovery" && !access) {
      toast.error("This link is not a password reset link.");
    }
    setReady(true);
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) {
      toast.error("Missing reset link", {
        description: "Open the latest password reset email and use that link.",
      });
      return;
    }
    if (password.length < 12) {
      toast.error("Password too short", { description: "Use at least 12 characters." });
      return;
    }
    if (password !== confirm) {
      toast.error("Passwords do not match");
      return;
    }
    setLoading(true);
    const res = await updatePassword(token, password);
    setLoading(false);
    if (res?.error || res?.ok === false) {
      toast.error("Could not update password", {
        description: res?.error || "Request a new reset link and try again.",
      });
      return;
    }
    toast.success("Password updated", { description: "Sign in with your new password." });
    navigate({ to: "/login" });
  };

  if (!ready) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-semibold tracking-tight">Set a new password</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {token
          ? "Choose a strong password of at least 12 characters."
          : "Open the reset link from your email first, then set a new password."}
      </p>
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-1.5">
          <Label htmlFor="pw">New password</Label>
          <Input
            id="pw"
            type="password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pw2">Confirm password</Label>
          <Input
            id="pw2"
            type="password"
            required
            minLength={12}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading || !token}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Update password"}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        <Link to="/forgot-password" className="font-medium text-primary hover:underline">
          Request a new reset link
        </Link>
        {" · "}
        <Link to="/login" className="font-medium text-primary hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
