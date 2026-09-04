import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Store, Users, KeyRound, MonitorSmartphone, Activity,
  CloudUpload, RefreshCw, AlertTriangle,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAdminOverview, GET } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/")({
  component: AdminDashboard,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function AdminDashboard() {
  const overviewQ = useQuery({
    queryKey: ["admin-overview"],
    queryFn: getAdminOverview,
    retry: 1,
  });
  const healthQ = useQuery({
    queryKey: ["admin-home-health"],
    queryFn: () => GET<{ score?: number; overall?: string }>("/health/detail"),
    retry: 1,
  });

  const data = overviewQ.data;
  const summary = data?.summary;
  const devices = data?.devices || [];
  const onlineCutoff = Date.now() - 5 * 60 * 1000;
  const onlineDevices = devices.filter((device) => {
    const seen = device.last_seen_at ? new Date(device.last_seen_at).getTime() : 0;
    return device.is_active !== false && Number.isFinite(seen) && seen >= onlineCutoff;
  }).length;
  const resourceErrors = Object.entries(data?.errors || {});
  const loadError = data?.error || (overviewQ.error as Error | null)?.message ||
    (resourceErrors.length
      ? resourceErrors.map(([resource, message]) => `${resource}: ${message}`).join(" · ")
      : "");
  const refresh = () => {
    void overviewQ.refetch();
    void healthQ.refetch();
  };

  return (
    <PageShell>
      <PageHeader
        eyebrow="Platform Admin"
        title="MugoByte Platform overview"
        description="Shared control plane for users, organizations, applications, devices, licenses and audit history."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={refresh} disabled={overviewQ.isFetching}>
              <RefreshCw className={`mr-1.5 h-4 w-4 ${overviewQ.isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/reports">Reports Center</Link>
            </Button>
          </>
        }
      />

      {loadError ? (
        <Card className="border-destructive/40">
          <CardContent className="flex gap-3 p-4 text-sm text-destructive">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <div>
              <div className="font-medium">Platform data could not be loaded</div>
              <div className="mt-1 text-muted-foreground">{loadError}</div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Organizations"
          value={overviewQ.isLoading ? "…" : String(summary?.organizations ?? 0)}
          icon={Store}
          hint={`${summary?.businesses ?? 0} registered businesses`}
          accent="primary"
        />
        <StatCard
          label="Active licenses"
          value={overviewQ.isLoading ? "…" : String(summary?.active_licenses ?? 0)}
          icon={KeyRound}
          hint={`${summary?.licenses ?? 0} total`}
          accent="success"
        />
        <StatCard
          label="Online devices"
          value={overviewQ.isLoading ? "…" : String(onlineDevices)}
          icon={MonitorSmartphone}
          hint={`${summary?.devices ?? 0} registered · seen within 5 min`}
          accent="info"
        />
        <StatCard
          label="Health score"
          value={healthQ.data?.score != null ? `${healthQ.data.score}%` : healthQ.isLoading ? "…" : "—"}
          icon={Users}
          hint={healthQ.data?.overall || "System health"}
          accent="warning"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="font-display">Organizations and shops</CardTitle>
            <CardDescription>Live Supabase roster. No local POS or demo shop records are mixed in.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(data?.organizations || []).slice(0, 8).map((org) => {
              const orgLicenses = (data?.licenses || []).filter((row) => row.org_id === org.id).length;
              const orgDevices = devices.filter((row) => row.org_id === org.id).length;
              return (
                <div key={org.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-4">
                  <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
                    <Store className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{org.name}</div>
                    <div className="text-xs text-muted-foreground">{org.slug || org.id}</div>
                  </div>
                  <Badge variant={org.status === "active" ? "default" : "secondary"}>{org.status || "unknown"}</Badge>
                  <div className="text-xs text-muted-foreground">{orgLicenses} licenses · {orgDevices} devices</div>
                </div>
              );
            })}
            {!overviewQ.isLoading && !loadError && (data?.organizations || []).length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">No organizations are registered.</p>
            ) : null}
            {(data?.organizations || []).length > 8 ? (
              <Button asChild variant="outline" size="sm"><Link to="/admin/shops">View all organizations</Link></Button>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-display">Platform activity</CardTitle>
            <CardDescription>Current live resource counts.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {[
              [Users, "Active members", summary?.members ?? 0],
              [CloudUpload, "Cloud backups", summary?.backups ?? 0],
              [MonitorSmartphone, "Enabled devices", summary?.enabled_devices ?? 0],
              [Activity, "Health", healthQ.data?.score != null ? `${healthQ.data.score}%` : "—"],
            ].map(([Icon, label, value]) => (
              <div key={String(label)} className="flex items-center gap-3 rounded-xl border border-border/70 p-3">
                <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" />
                </div>
                <span className="min-w-0 flex-1 font-medium">{String(label)}</span>
                <Badge variant="secondary">{String(value)}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}
