import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, AlertTriangle, XCircle, RefreshCw } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/system-health")({
  component: SystemHealthPage,
  head: () => ({ meta: [{ title: "System Health | MugoByte" }] }),
});

type HealthCheck = {
  id: string;
  name: string;
  ok: boolean;
  detail: string;
  weight: number;
  warn?: boolean;
};

type HealthData = {
  score: number;
  overall: "healthy" | "warn" | "err";
  checks: HealthCheck[];
  time: string;
  version?: { version?: string; build?: string };
};

function SystemHealthPage() {
  const healthQ = useQuery({
    queryKey: ["system-health"],
    queryFn: () => GET<HealthData>("/health/detail"),
    refetchInterval: 30_000,
  });

  const data = healthQ.data;
  const overall = data?.overall || "unknown";
  const score = data?.score ?? 0;

  function StatusIcon({ ok, warn }: { ok: boolean; warn?: boolean }) {
    if (ok && !warn) return <CheckCircle2 className="h-4 w-4 text-success" />;
    if (ok && warn) return <AlertTriangle className="h-4 w-4 text-warning" />;
    return <XCircle className="h-4 w-4 text-destructive" />;
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="System Health"
        description="Live status of every MBT POS subsystem — API, database, storage, backups, sync and security."
        actions={
          <Button variant="outline" onClick={() => healthQ.refetch()} disabled={healthQ.isFetching}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${healthQ.isFetching ? "animate-spin" : ""}`} />
            {healthQ.isFetching ? "Checking…" : "Refresh"}
          </Button>
        }
      />

      {healthQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Running health checks…</CardContent></Card>
      ) : healthQ.error || !data ? (
        <Card><CardContent className="p-6 text-sm text-destructive">Failed to load system health. Check your network or backend server.</CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card className={overall === "healthy" ? "border-success/30" : overall === "warn" ? "border-warning/30" : "border-destructive/30"}>
              <CardContent className="p-5">
                <div className="flex items-center justify-between">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Overall health</div>
                  <Badge variant={overall === "healthy" ? "default" : overall === "warn" ? "secondary" : "destructive"}>
                    {overall}
                  </Badge>
                </div>
                <div className="mt-4 font-display text-4xl font-bold">{score}%</div>
                <Progress value={score} className="mt-3 h-2" />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Checks passing</div>
                <div className="mt-4 font-display text-4xl font-bold text-success">
                  {data.checks.filter((c) => c.ok && !c.warn).length}
                  <span className="ml-1 text-xl text-muted-foreground">/ {data.checks.length}</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-5">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Last checked</div>
                <div className="mt-4 font-display text-lg font-semibold">
                  {data.time ? data.time.slice(11, 19) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">{data.time?.slice(0, 10) || "—"}</div>
                {data.version?.version && (
                  <div className="mt-2 text-xs text-muted-foreground">v{data.version.version}</div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Service checks</CardTitle>
              <CardDescription>Individual subsystem status and diagnostics.</CardDescription>
            </CardHeader>
            <CardContent className="divide-y divide-border/50">
              {data.checks.map((c) => (
                <div key={c.id} className="flex items-center gap-4 py-4">
                  <StatusIcon ok={c.ok} warn={c.warn} />
                  <div className="flex-1">
                    <div className="font-medium">{c.name}</div>
                    <div className="text-sm text-muted-foreground">{c.detail}</div>
                  </div>
                  <Badge variant={c.ok && !c.warn ? "default" : c.warn ? "secondary" : "destructive"}>
                    {c.ok && !c.warn ? "OK" : c.warn ? "Warn" : "Error"}
                  </Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}
