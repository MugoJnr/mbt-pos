import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Loader2, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { resendVerification } from "@/lib/api";

type VerifySearch = { email?: string };

export const Route = createFileRoute("/_auth/verify-email")({
  head: () => ({ meta: [{ title: "Verify Email | MugoByte" }] }),
  validateSearch: (search: Record<string, unknown>): VerifySearch => ({
    email: typeof search.email === "string" ? search.email : undefined,
  }),
  component: VerifyPage,
});

function VerifyPage() {
  const { email: emailFromSearch } = Route.useSearch();
  const [email, setEmail] = useState(emailFromSearch || "");
  const [loading, setLoading] = useState(false);
  const hasEmail = useMemo(() => email.trim().includes("@"), [email]);

  const onResend = async () => {
    const trimmed = email.trim().toLowerCase();
    if (!trimmed.includes("@")) {
      toast.error("Email required", { description: "Enter the address you registered with." });
      return;
    }
    setLoading(true);
    const res = await resendVerification(trimmed);
    setLoading(false);
    if (res?.error) {
      toast.error("Could not resend", { description: res.error });
      return;
    }
    toast.success("Verification email sent", {
      description: "Check your inbox (and spam) for the confirmation link.",
    });
  };

  return (
    <div className="animate-fade-in text-center">
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
        <MailCheck className="h-6 w-6" />
      </div>
      <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight">Verify your email</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        We've sent a verification link to your inbox. Click it to activate your MugoByte Platform account.
      </p>
      <div className="mx-auto mt-6 max-w-sm space-y-3 text-left">
        <div className="space-y-1.5">
          <Label htmlFor="verify-email">Email</Label>
          <Input
            id="verify-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@business.com"
            autoComplete="email"
          />
        </div>
        <Button className="w-full" variant="outline" onClick={onResend} disabled={loading || !hasEmail}>
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Sending…
            </>
          ) : (
            "Resend email"
          )}
        </Button>
        <Button asChild variant="ghost" className="w-full">
          <Link to="/login">Back to sign in</Link>
        </Button>
      </div>
    </div>
  );
}
