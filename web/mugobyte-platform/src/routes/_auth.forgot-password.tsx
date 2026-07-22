import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { forgotPassword } from "@/lib/api";

export const Route = createFileRoute("/_auth/forgot-password")({
  head: () => ({ meta: [{ title: "Forgot Password | MugoByte" }] }),
  component: ForgotPage,
});

function ForgotPage() {
  const [email, setEmail] = useState("eugenemugo@gmail.com");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = email.trim().toLowerCase();
    if (!trimmed.includes("@")) {
      toast.error("Enter a valid email address");
      return;
    }
    setLoading(true);
    const res = await forgotPassword(trimmed);
    setLoading(false);
    setSent(true);
    toast.success("Check your inbox", {
      description: res?.message || "If that email exists, a reset link was sent.",
    });
  };

  return (
    <div className="animate-fade-in">
      <Link
        to="/login"
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
      </Link>
      <h1 className="font-display text-2xl font-semibold tracking-tight">Forgot password</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Enter your account email and we will send a secure reset link.
      </p>
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send reset link"}
        </Button>
      </form>
      {sent && (
        <p className="mt-4 text-sm text-muted-foreground">
          Open the email from MugoByte, click the reset link, then choose a new password.
        </p>
      )}
    </div>
  );
}
