import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_auth/forgot-password")({
  head: () => ({ meta: [{ title: "Forgot Password | MugoByte" }] }),
  component: ForgotPage,
});

function ForgotPage() {
  return (
    <div className="animate-fade-in">
      <Link to="/login" className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
      </Link>
      <h1 className="font-display text-2xl font-semibold tracking-tight">Forgot password</h1>
      <p className="mt-1 text-sm text-muted-foreground">Enter your account email and we will send a secure reset link.</p>
      <form className="mt-6 space-y-4" onSubmit={(e) => { e.preventDefault(); toast.success("Reset link prepared", { description: "The backend reset flow is reserved for centralized platform auth." }); }}>
        <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" required /></div>
        <Button type="submit" className="w-full">Send reset link</Button>
      </form>
    </div>
  );
}
