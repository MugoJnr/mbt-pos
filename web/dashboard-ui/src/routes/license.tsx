import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, Cpu, CalendarClock, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, PageHeader, SectionTitle, Skeleton } from "@/components/ui-kit";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/license")({
  component: License,
});

function toneForState(state?: string): "ok" | "warn" | "err" | "muted" | "gold" {
  const s = (state || "").toLowerCase();
  if (s === "active" || s === "expiring") return "ok";
  if (s === "warning" || s === "critical") return "warn";
  if (s === "expired" || s === "tampered" || s === "inactive") return "err";
  if (s === "unactivated") return "muted";
  return "gold";
}

function License() {
  const licQ = useQuery({
    queryKey: ["license-status"],
    queryFn: () => GET<any>("/license/status"),
  });
  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<any>("/version"),
  });

  const lic = licQ.data || {};
  const err = lic.error && !lic.plan_name ? lic.error : null;
  const forbidden = lic.error === "Forbidden";
  const state = String(lic.state || "unknown");
  const planName = lic.plan_name || lic.plan || "—";
  const expiry = lic.expiry_date || "—";
  const device = lic.device_id || "—";
  const days = lic.days_remaining;
  const ver = versionQ.data?.version || "—";

  return (
    <AppShell title="License">
      <PageHeader
        eyebrow="Admin"
        title="License & Subscription"
        description="Live status from this installation’s license engine."
      />
      {forbidden ? (
        <Card className="p-6 text-sm text-text2">
          Manager or admin access is required to view license details.
        </Card>
      ) : licQ.isLoading ? (
        <Card className="p-6 space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-20 w-full" />
        </Card>
      ) : (
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
                <div className="text-xl font-bold text-text">{planName}</div>
              </div>
              <div className="ml-auto">
                <Badge tone={toneForState(state)}>{state.toUpperCase()}</Badge>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
              <Info
                icon={<CalendarClock className="h-4 w-4" />}
                label="Expiry"
                value={
                  expiry +
                  (days != null && days !== "" ? ` · ${days}d left` : "")
                }
              />
              <Info
                icon={<Cpu className="h-4 w-4" />}
                label="Hardware / Device"
                value={String(device)}
                mono
              />
              <Info
                icon={<KeyRound className="h-4 w-4" />}
                label="App version"
                value={`v${ver}`}
                mono
              />
            </div>

            <SectionTitle>Activation</SectionTitle>
            <p className="text-sm text-text2 leading-relaxed">
              Activate or renew licenses from the desktop License tab or via Telegram support
              (@MugoByteSupport). This page shows the verified status for the current machine
              {lic.source ? ` (source: ${lic.source})` : ""}.
            </p>
            {err || lic.error ? (
              <p className="text-xs text-warn mt-3">
                Note: {String(err || lic.error)}
              </p>
            ) : null}
          </Card>

          <Card className="p-6">
            <SectionTitle>Validity</SectionTitle>
            <ul className="space-y-2 text-sm text-text2">
              <li>
                Valid for use:{" "}
                <strong className="text-text">{lic.is_valid ? "Yes" : "No"}</strong>
              </li>
              <li>
                Activation date:{" "}
                <strong className="text-text">{lic.activation_date || "—"}</strong>
              </li>
              <li>
                Plan code: <strong className="text-text font-mono">{lic.plan || "—"}</strong>
              </li>
            </ul>
          </Card>
        </div>
      )}
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
