import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { getUser, isPlatformAdmin } from "@/lib/api";

export const Route = createFileRoute("/_auth/login")({
  component: LoginPage,
  validateSearch: (search: Record<string, unknown>) => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
    next: typeof search.next === "string" ? search.next : undefined,
  }),
  head: () => ({ meta: [{ title: "Sign In | MugoByte" }] }),
});

function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(() => {
    try {
      return localStorage.getItem("mbt_remember") !== "0";
    } catch {
      return true;
    }
  });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const error = await login(username.trim(), password, remember);
    setLoading(false);
    if (error) {
      toast.error("Sign in failed", { description: error });
      return;
    }
    toast.success("Welcome back", { description: "Opening your MugoByte Workspace…" });
    const params = new URLSearchParams(window.location.search);
    const next = params.get("redirect") || params.get("next") || "";
    if (next.startsWith("/") && !next.startsWith("//")) {
      window.location.assign(next);
      return;
    }
    if (isPlatformAdmin(getUser())) {
      navigate({ to: "/admin/licenses" });
      return;
    }
    navigate({ to: "/dashboard" });
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-5 rounded-xl border border-primary/20 bg-primary/5 px-3.5 py-2.5 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">MugoByte Workspace</span>
        <span className="mx-1.5 text-border">·</span>
        Secure cloud account for every MugoByte product
      </div>
      <h1 className="font-display text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        One account for every MugoByte product — enter your Workspace, not just a POS screen.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email or username</Label>
          <Input id="email" value={username} onChange={(e) => setUsername(e.target.value)} required placeholder="you@business.com" autoComplete="username" />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link to="/forgot-password" className="text-xs text-primary hover:underline">Forgot password?</Link>
          </div>
          <div className="relative">
            <Input id="password" type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" className="pr-10" />
            <button type="button" aria-label={show ? "Hide password" : "Show password"} className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground" onClick={() => setShow((s) => !s)}>
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Checkbox
              checked={remember}
              onCheckedChange={(value) => setRemember(value === true)}
            />
            Remember me
          </label>
          <Link to="/verify-email" className="text-xs text-muted-foreground hover:text-foreground">Verify account</Link>
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Signing in</> : "Sign in"}
        </Button>
      </form>

      <div className="my-6 flex items-center gap-3">
        <Separator className="flex-1" />
        <span className="text-[11px] uppercase tracking-widest text-muted-foreground">Shared access</span>
        <Separator className="flex-1" />
      </div>

      <div className="rounded-xl border border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
        After sign-in you land in MugoByte Workspace: products, businesses, devices, reports and cloud tools — Live Dashboard stays on your shop tunnel.
      </div>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        New to the platform? <Link to="/register" className="font-medium text-primary hover:underline">Create an account</Link>
      </p>
    </div>
  );
}
