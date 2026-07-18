import { createFileRoute } from "@tanstack/react-router";
import { KeyRound, Cpu, CalendarClock, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, SectionTitle } from "@/components/ui-kit";

export const Route = createFileRoute("/license")({
  component: License,
});

function License() {
  return (
    <AppShell title="License">
      <PageHeader
        eyebrow="Admin"
        title="License & Subscription"
        description="Plan status and activation for this installation."
      />
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-4">
        <Card className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="h-11 w-11 rounded-md grid place-items-center bg-gold/15 text-gold">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">
                Current Plan
              </div>
              <div className="text-xl font-bold text-text">MBT POS · Business</div>
            </div>
            <div className="ml-auto">
              <Badge tone="ok">ACTIVE</Badge>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
            <Info icon={<CalendarClock className="h-4 w-4" />} label="Expiry" value="14 Aug 2027" />
            <Info icon={<Cpu className="h-4 w-4" />} label="Hardware ID" value="HW-8F3A-2C41-90BD" mono />
            <Info icon={<KeyRound className="h-4 w-4" />} label="License Key" value="MBT-BSN-••••-4A9K" mono />
          </div>

          <SectionTitle>Activate a new key</SectionTitle>
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 mb-3">
            <Input placeholder="XXXX-XXXX-XXXX-XXXX" />
            <Button variant="primary">Activate</Button>
          </div>
          <p className="text-xs text-text2">
            You can also request activation via Telegram. Send your Hardware ID to
            <span className="text-gold font-semibold"> @MugoByteSupport</span>.
          </p>
        </Card>

        <Card className="p-6">
          <SectionTitle>Renew / Upgrade</SectionTitle>
          <ul className="space-y-2 mb-4 text-sm">
            {[
              ["Starter", "KES 6,000/yr"],
              ["Business", "KES 18,000/yr", true],
              ["Enterprise", "KES 42,000/yr"],
            ].map(([n, p, current]) => (
              <li
                key={n as string}
                className={`flex items-center justify-between rounded-md border p-3 ${
                  current ? "border-gold bg-gold/10" : "border-border bg-card2"
                }`}
              >
                <div>
                  <div className="text-sm font-semibold text-text">{n}</div>
                  <div className="text-xs text-text2">{p}</div>
                </div>
                {current ? (
                  <Badge tone="gold">Current</Badge>
                ) : (
                  <Button size="sm" variant="secondary">
                    Select
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <Button variant="primary" className="w-full">
            Renew License
          </Button>
        </Card>
      </div>
    </AppShell>
  );
}

function Info({
  icon,
  label,
  value,
  mono,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border border-border bg-card2 p-3">
      <div className="flex items-center gap-1.5 text-[10px] tracking-[0.16em] uppercase font-semibold text-text2">
        <span className="text-gold">{icon}</span>
        {label}
      </div>
      <div className={`mt-1 text-sm font-semibold text-text ${mono ? "font-mono" : ""}`}>
        {value}
      </div>
    </div>
  );
}
