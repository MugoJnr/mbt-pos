import { createFileRoute } from "@tanstack/react-router";
import { ShieldCheck, Lock, KeyRound, ScrollText } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, SectionTitle } from "@/components/ui-kit";

export const Route = createFileRoute("/security")({
  component: Security,
});

function Security() {
  return (
    <AppShell title="Security">
      <PageHeader
        eyebrow="Admin"
        title="Security"
        description="PIN policy, auto-lock, and audit visibility for managers."
        icon={<ShieldCheck className="h-5 w-5 text-gold" />}
      />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {[
          { k: "PIN Policy", v: "Strong", tone: "ok" as const, i: <KeyRound className="h-5 w-5" /> },
          { k: "Auto-Lock", v: "5 min", tone: "info" as const, i: <Lock className="h-5 w-5" /> },
          { k: "Audit Log", v: "Enabled", tone: "ok" as const, i: <ScrollText className="h-5 w-5" /> },
        ].map((s) => (
          <Card key={s.k} className="p-5 flex items-center gap-4">
            <div className="h-11 w-11 rounded-md grid place-items-center bg-gold/15 text-gold">
              {s.i}
            </div>
            <div className="flex-1">
              <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">
                {s.k}
              </div>
              <div className="text-xl font-bold text-text mt-0.5">{s.v}</div>
            </div>
            <Badge tone={s.tone}>OK</Badge>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <SectionTitle>PIN & Password Policy</SectionTitle>
          <div className="space-y-4">
            {[
              ["Minimum PIN length", "6"],
              ["Password rotation (days)", "90"],
              ["Failed attempts before lockout", "5"],
              ["Session timeout (minutes)", "15"],
            ].map(([l, v]) => (
              <label key={l} className="flex items-center justify-between gap-4">
                <span className="text-sm text-text">{l}</span>
                <Input defaultValue={v} className="w-32 text-right" />
              </label>
            ))}
            <Button variant="primary">Update Policy</Button>
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle>Superadmin Actions</SectionTitle>
          <div className="space-y-3">
            <ActionRow
              icon={<ShieldCheck className="h-4 w-4" />}
              title="Rotate Super-Admin PIN"
              desc="Force a fresh 6-digit PIN"
              cta="Rotate"
            />
            <ActionRow
              icon={<Lock className="h-4 w-4" />}
              title="Lock all sessions"
              desc="Force sign-out on every device"
              cta="Lock now"
              tone="danger"
            />
            <ActionRow
              icon={<ScrollText className="h-4 w-4" />}
              title="Export Audit Log"
              desc="Last 90 days of privileged actions"
              cta="Export"
            />
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function ActionRow({
  icon,
  title,
  desc,
  cta,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
  cta: string;
  tone?: "danger";
}) {
  return (
    <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border bg-card2">
      <div className="flex items-start gap-3">
        <span className="h-8 w-8 rounded-md grid place-items-center bg-gold/15 text-gold">
          {icon}
        </span>
        <div>
          <div className="text-sm font-semibold text-text">{title}</div>
          <div className="text-xs text-text2">{desc}</div>
        </div>
      </div>
      <Button size="sm" variant={tone === "danger" ? "danger" : "secondary"}>
        {cta}
      </Button>
    </div>
  );
}
