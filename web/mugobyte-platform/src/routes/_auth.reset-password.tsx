import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_auth/reset-password")({
  head: () => ({ meta: [{ title: "Reset Password | MugoByte" }] }),
  component: ResetPage,
});

function ResetPage() {
  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-semibold tracking-tight">Set a new password</h1>
      <p className="mt-1 text-sm text-muted-foreground">Choose a strong password of at least 8 characters.</p>
      <form className="mt-6 space-y-4" onSubmit={(e) => e.preventDefault()}>
        <div className="space-y-1.5"><Label htmlFor="pw">New password</Label><Input id="pw" type="password" required /></div>
        <div className="space-y-1.5"><Label htmlFor="pw2">Confirm password</Label><Input id="pw2" type="password" required /></div>
        <Button type="submit" className="w-full">Update password</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        <Link to="/login" className="font-medium text-primary hover:underline">Back to sign in</Link>
      </p>
    </div>
  );
}
