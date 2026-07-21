import { createFileRoute } from "@tanstack/react-router";
import { InputOTP, InputOTPGroup, InputOTPSeparator, InputOTPSlot } from "@/components/ui/input-otp";
import { Button } from "@/components/ui/button";
import { ShieldCheck } from "lucide-react";

export const Route = createFileRoute("/_auth/two-factor")({
  head: () => ({ meta: [{ title: "Two-Factor | MugoByte" }] }),
  component: TwoFactorPage,
});

function TwoFactorPage() {
  return (
    <div className="animate-fade-in">
      <div className="grid h-11 w-11 place-items-center rounded-lg bg-primary/10 text-primary">
        <ShieldCheck className="h-5 w-5" />
      </div>
      <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight">Two-factor authentication</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Enter the 6-digit code from your authenticator app.
      </p>
      <div className="mt-6 flex justify-center">
        <InputOTP maxLength={6}>
          <InputOTPGroup>
            <InputOTPSlot index={0} /><InputOTPSlot index={1} /><InputOTPSlot index={2} />
          </InputOTPGroup>
          <InputOTPSeparator />
          <InputOTPGroup>
            <InputOTPSlot index={3} /><InputOTPSlot index={4} /><InputOTPSlot index={5} />
          </InputOTPGroup>
        </InputOTP>
      </div>
      <Button className="mt-6 w-full">Verify & continue</Button>
      <button type="button" className="mt-3 w-full text-center text-xs text-muted-foreground hover:text-foreground">
        Use a recovery code instead
      </button>
    </div>
  );
}
