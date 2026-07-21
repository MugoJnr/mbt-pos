import { createFileRoute, Link } from "@tanstack/react-router";
import { TimerReset } from "lucide-react";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_auth/session-expired")({
  head: () => ({ meta: [{ title: "Session Expired | MugoByte" }] }),
  component: SessionExpiredPage,
});

function SessionExpiredPage() {
  return (
    <div className="animate-fade-in text-center">
      <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-warning/15 text-warning">
        <TimerReset className="h-6 w-6" />
      </div>
      <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight">Session expired</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        For your security, we signed you out due to inactivity. Please sign in again to continue.
      </p>
      <Button asChild className="mt-6 w-full"><Link to="/login">Sign in again</Link></Button>
    </div>
  );
}
