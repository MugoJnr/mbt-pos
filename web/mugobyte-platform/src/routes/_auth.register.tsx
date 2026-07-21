import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_auth/register")({
  head: () => ({ meta: [{ title: "Create Account | MugoByte" }] }),
  component: RegisterPage,
});

function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [loading, setLoading] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [business, setBusiness] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail.includes("@")) {
      toast.error("Invalid email", { description: "Enter a valid work email address." });
      return;
    }
    if (password.length < 12) {
      toast.error("Password too short", { description: "Use at least 12 characters." });
      return;
    }
    setLoading(true);
    const fullName = `${firstName.trim()} ${lastName.trim()}`.trim();
    const error = await register({
      email: trimmedEmail,
      password,
      full_name: fullName || undefined,
      business_name: business.trim() || undefined,
    });
    setLoading(false);
    if (error === "VERIFY_EMAIL") {
      toast.success("Check your inbox", {
        description: "We sent a verification link. Confirm your email, then sign in.",
      });
      navigate({
        to: "/verify-email",
        search: { email: trimmedEmail },
      });
      return;
    }
    if (error) {
      toast.error("Registration failed", { description: error });
      return;
    }
    toast.success("Account created", { description: "Opening your MugoByte Workspace…" });
    navigate({ to: "/dashboard" });
  };

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-semibold tracking-tight">Create account</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Register once for MugoByte Platform, then connect your businesses and applications.
      </p>

      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="fn">First name</Label>
            <Input id="fn" required value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ln">Last name</Label>
            <Input id="ln" required value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="biz">Organization / Business name</Label>
          <Input
            id="biz"
            required
            placeholder="ABC Supermarket"
            value={business}
            onChange={(e) => setBusiness(e.target.value)}
            autoComplete="organization"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Work email</Label>
          <Input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="phone">Phone</Label>
          <Input
            id="phone"
            type="tel"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pw">Password</Label>
          <Input
            id="pw"
            type="password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <p className="text-xs text-muted-foreground">At least 12 characters.</p>
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Creating account...
            </>
          ) : (
            "Create account"
          )}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Already registered?{" "}
        <Link to="/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
