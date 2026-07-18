import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { HeartPulse, CheckCircle2, AlertTriangle, XCircle, HelpCircle } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, SectionTitle } from "@/components/ui-kit";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/health")({
  component: HealthPage,
});

type Check = {
  key: string;
  label: string;
  state: "healthy" | "warn" | "err" | string;
  detail: string;
};

function HealthPage() {
  const healthQ = useQuery({
    queryKey: ["health-detail"],
    queryFn: () => GET<{ score: number; overall: string; checks: Check[]; version?: any }>("/health/detail"),
    refetchInterval: 30_000,
  });
  const data = healthQ.data;
  const score = Number(data?.score ?? 0);
  const checks = Array.isArray(data?.checks) ? data!.checks : [];
  const overall = data?.overall || "unknown";

  const ringColor =
    overall === "healthy" ? "stroke-ok" : overall === "warn" ? "stroke-warn" : "stroke-err";

  return (
    <AppShell title="System Health">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-xl font-bold text-text flex items-center gap-2">
            <HeartPulse className="h-5 w-5 text-gold" /> System Health
          </h2>
          <p className="text-sm text-text2">Scored checks across DB, storage, cloud, AI & more</p>
        </div>
        <Button variant="secondary" onClick={() => healthQ.refetch()}>
          Re-run checks
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4 mb-4">
        <Card className="p-5 flex flex-col items-center justify-center">
          <div className="relative h-36 w-36">
            <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100">
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                className="stroke-border"
                strokeWidth="8"
              />
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                className={ringColor}
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${(score / 100) * 264} 264`}
              />
            </svg>
            <div className="absolute inset-0 grid place-items-center">
              <div className="text-center">
                <div className="text-3xl font-extrabold text-text">{score}</div>
                <div className="text-[10px] tracking-[0.16em] text-text2 uppercase">Score</div>
              </div>
            </div>
          </div>
          <Badge
            tone={
              overall === "healthy" ? "ok" : overall === "warn" ? "warn" : "err"
            }
          >
            {String(overall).toUpperCase()}
          </Badge>
          {data?.version?.version ? (
            <div className="mt-2 text-xs text-text2 font-mono">v{data.version.version}</div>
          ) : null}
        </Card>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {healthQ.isLoading
            ? Array.from({ length: 8 }).map((_, i) => (
                <Card key={i} className="p-4 h-24 animate-pulse bg-panel/40" />
              ))
            : checks.map((c) => <HealthCheckCard key={c.key} check={c} />)}
        </div>
      </div>

      <Card className="p-4 flex flex-wrap gap-4 text-sm">
        <Link to="/diagnostics" className="text-gold font-semibold">
          Open Diagnostics →
        </Link>
        <Link to="/backup" className="text-gold font-semibold">
          Backup Center →
        </Link>
        <Link to="/live" className="text-gold font-semibold">
          Live Monitoring →
        </Link>
      </Card>
    </AppShell>
  );
}

function HealthCheckCard({ check }: { check: Check }) {
  const Icon =
    check.state === "healthy"
      ? CheckCircle2
      : check.state === "warn"
        ? AlertTriangle
        : check.state === "err"
          ? XCircle
          : HelpCircle;
  const tone =
    check.state === "healthy" ? "ok" : check.state === "warn" ? "warn" : check.state === "err" ? "err" : "muted";
  return (
    <Card className="p-4">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <Icon className={`h-4 w-4 text-${tone}`} />
          {check.label}
        </span>
      </SectionTitle>
      <Badge tone={tone as any}>{String(check.state).toUpperCase()}</Badge>
      <div className="mt-2 text-xs text-text2 leading-relaxed">{check.detail}</div>
    </Card>
  );
}
