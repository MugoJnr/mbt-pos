import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Play, Download, RotateCw, CheckCircle2, HelpCircle, HeartPulse } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card } from "@/components/ui-kit";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/diagnostics")({
  component: Diagnostics,
});

const TABS = ["Diagnostic Log", "App Log", "Sync Queue"] as const;

function Diagnostics() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Diagnostic Log");
  const healthQ = useQuery({
    queryKey: ["health-detail"],
    queryFn: () => GET<any>("/health/detail"),
  });
  const syncQ = useQuery({
    queryKey: ["sync-pending"],
    queryFn: () => GET<any[]>("/sync/pending"),
  });
  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<any>("/version"),
  });

  const checks = Array.isArray(healthQ.data?.checks) ? healthQ.data.checks : [];
  const syncItems = Array.isArray(syncQ.data) ? syncQ.data : [];
  const now = new Date().toLocaleTimeString("en-GB", { hour12: false });

  const logs: Record<(typeof TABS)[number], string[]> = {
    "Diagnostic Log": [
      `[${now}] Running diagnostics…`,
      ...checks.map(
        (c: any) =>
          `[${now}] ${c.label}: ${String(c.state).toUpperCase()} — ${c.detail}`,
      ),
      `[${now}] Overall score: ${healthQ.data?.score ?? "—"} (${healthQ.data?.overall || "—"})`,
    ],
    "App Log": [
      `[${now}] MBT POS web dashboard v${versionQ.data?.version || "2.3.87"}`,
      `[${now}] Build ${versionQ.data?.build || "—"}`,
      `[${now}] Health API: ${healthQ.isSuccess ? "ok" : healthQ.isError ? "error" : "…"}`,
    ],
    "Sync Queue":
      syncItems.length === 0
        ? [`[${now}] Sync queue empty`]
        : syncItems.slice(0, 40).map(
            (i: any) =>
              `[${i.status || "QUEUED"}] ${i.action || i.type || "item"} id=${i.id}`,
          ),
  };

  return (
    <AppShell title="Diagnostics">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-xl font-bold text-text">System Diagnostics</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/health">
            <Button variant="primary">
              <HeartPulse className="h-4 w-4" /> Health Score
            </Button>
          </Link>
          <Button variant="secondary" onClick={() => healthQ.refetch()}>
            <Play className="h-4 w-4" /> Run Check
          </Button>
          <Button variant="ghost" disabled title="Export via desktop logs">
            <Download className="h-4 w-4" /> Export
          </Button>
          <Button variant="ghost" disabled>
            <RotateCw className="h-4 w-4" /> Rotate Logs
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {(checks.length ? checks.slice(0, 4) : [
          { label: "Database", state: "unknown", detail: "Loading…" },
          { label: "Storage", state: "unknown", detail: "Loading…" },
          { label: "API", state: "unknown", detail: "Loading…" },
          { label: "Sync", state: "unknown", detail: "Loading…" },
        ]).map((c: any) => (
          <HealthCard
            key={c.key || c.label}
            label={c.label}
            state={c.state === "healthy" ? "healthy" : c.state === "warn" ? "warn" : c.state === "err" ? "err" : "unknown"}
            note={c.detail || c.note || ""}
          />
        ))}
      </div>

      <div
        className={`font-semibold text-sm mb-4 ${
          healthQ.data?.overall === "healthy"
            ? "text-ok"
            : healthQ.data?.overall === "warn"
              ? "text-warn"
              : "text-text2"
        }`}
      >
        Overall: {String(healthQ.data?.overall || "…").toUpperCase()} · score{" "}
        {healthQ.data?.score ?? "—"}
      </div>

      <Card className="overflow-hidden">
        <div className="flex overflow-x-auto border-b border-border">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-4 py-3 text-sm font-semibold whitespace-nowrap min-h-[44px] ${
                tab === t ? "text-gold" : "text-text2 hover:text-text"
              }`}
            >
              {t}
              {tab === t && <span className="absolute left-3 right-3 -bottom-px h-0.5 bg-gold" />}
            </button>
          ))}
        </div>

        <pre className="font-mono text-[12.5px] leading-relaxed p-5 bg-app text-text2 min-h-[280px] whitespace-pre-wrap overflow-x-auto">
          {logs[tab].join("\n")}
        </pre>
      </Card>
    </AppShell>
  );
}

function HealthCard({
  label,
  state,
  note,
}: {
  label: string;
  state: "healthy" | "warn" | "err" | "unknown";
  note: string;
}) {
  const tone =
    state === "healthy" ? "ok" : state === "warn" ? "warn" : state === "err" ? "err" : "muted";
  const text =
    state === "healthy"
      ? "HEALTHY"
      : state === "warn"
        ? "WARNING"
        : state === "err"
          ? "FAILING"
          : "UNKNOWN";
  const Icon = state === "healthy" ? CheckCircle2 : HelpCircle;
  return (
    <Card className="p-4">
      <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">
        {label}
      </div>
      <div className={`mt-2 flex items-center gap-2 text-${tone}`}>
        <Icon className="h-4 w-4" />
        <Badge tone={tone as any}>{text}</Badge>
      </div>
      <div className="mt-2 text-xs text-text2">{note}</div>
    </Card>
  );
}
