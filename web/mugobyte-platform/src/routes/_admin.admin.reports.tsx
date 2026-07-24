import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3, RefreshCw, KeyRound, MonitorSmartphone, Activity, ExternalLink, ShieldCheck,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  GET,
  listCloudLicenses,
  listCloudDevices,
  type CloudLicense,
  type CloudDevice,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_admin/admin/reports")({
  component: AdminReportsPage,
  head: () => ({ meta: [{ title: "Admin Reports | MugoByte" }] }),
});

type HealthData = {
  score?: number;
  overall?: string;
  checks?: Array<{ id: string; name: string; ok: boolean; warn?: boolean }>;
  time?: string;
  version?: { version?: string };
};

function AdminReportsPage() {
  const { orgId } = useAuth();

  const licensesQ = useQuery({
    queryKey: ["admin-reports-licenses", orgId],
    queryFn: () => listCloudLicenses(orgId),
  });
  const devicesQ = useQuery({
    queryKey: ["admin-reports-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
  });
  const healthQ = useQuery({
    queryKey: ["admin-reports-health"],
    queryFn: () => GET<HealthData>("/health/detail"),
    retry: 1,
  });
  const analyticsQ = useQuery({
    queryKey: ["admin-reports-analytics", orgId],
    queryFn: () =>
      GET<Record<string, unknown>>("/cloud/analytics/overview", {
        org_id: orgId,
      }),
    enabled: Boolean(orgId),
    retry: 0,
  });

  const licenses: CloudLicense[] = licensesQ.data?.licenses || [];
  const devices: CloudDevice[] = devicesQ.data?.devices || [];
  const health = healthQ.data;
  const scope = licensesQ.data?.scope || "org";

  const activeLic = licenses.filter((l) => {
    const s = (l.status || "").toLowerCase();
    return s === "active" || s === "trial";
  }).length;
  const suspendedLic = licenses.filter((l) => (l.status || "").toLowerCase() === "suspended").length;
  const claimed = licenses.filter((l) => (l.claim_status || "").toLowerCase() === "claimed").length;
  const reserved = licenses.filter((l) => (l.claim_status || "").toLowerCase() === "reserved").length;
  const unassigned = licenses.filter((l) => {
    const c = (l.claim_status || "unassigned").toLowerCase();
    return c === "unassigned" || !l.claim_status;
  }).length;
  const hwLocked = licenses.filter((l) => Boolean((l.reserved_device_id || "").trim())).length;
  const seatsUsed = licenses.reduce((n, l) => n + Number(l.activated_devices || 0), 0);
  const seatsMax = licenses.reduce((n, l) => n + Number(l.max_devices || 1), 0);
  const devicesActive = devices.filter((d) => d.is_active !== false).length;

  const summary = (analyticsQ.data?.summary || analyticsQ.data?.kpis || analyticsQ.data || {}) as Record<string, unknown>;
  const gross = Number(summary.gross_sales ?? summary.sales_total ?? summary.revenue ?? NaN);
  const txns = Number(summary.transactions ?? summary.sales_count ?? summary.receipts ?? NaN);
  const analyticsOk = !analyticsQ.isError && analyticsQ.data && !analyticsQ.data.error;

  const refresh = () => {
    void licensesQ.refetch();
    void devicesQ.refetch();
    void healthQ.refetch();
    if (orgId) void analyticsQ.refetch();
  };

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Reports Center"
        description="Platform overview across licenses, devices, health, and org sales analytics."
        actions={
          <Button variant="outline" onClick={refresh} disabled={licensesQ.isFetching || devicesQ.isFetching}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${licensesQ.isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList className="mb-4 h-auto flex-wrap justify-start">
          <TabsTrigger value="overview"><BarChart3 className="mr-1.5 h-3.5 w-3.5" />Overview</TabsTrigger>
          <TabsTrigger value="licenses"><KeyRound className="mr-1.5 h-3.5 w-3.5" />Licenses</TabsTrigger>
          <TabsTrigger value="devices"><MonitorSmartphone className="mr-1.5 h-3.5 w-3.5" />Devices</TabsTrigger>
          <TabsTrigger value="sales"><Activity className="mr-1.5 h-3.5 w-3.5" />Sales</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Licenses"
              value={String(licenses.length)}
              icon={KeyRound}
              hint={scope === "all" ? "All organizations" : "This organization"}
              accent="primary"
            />
            <StatCard
              label="Active / trial"
              value={String(activeLic)}
              icon={ShieldCheck}
              hint={`${suspendedLic} suspended`}
              accent="success"
            />
            <StatCard
              label="Devices"
              value={String(devices.length)}
              icon={MonitorSmartphone}
              hint={`${devicesActive} active`}
              accent="info"
            />
            <StatCard
              label="Health"
              value={health?.score != null ? `${health.score}%` : "—"}
              icon={Activity}
              hint={health?.overall || (healthQ.isError ? "Auth or unavailable" : "Loading…")}
              accent={health?.overall === "healthy" ? "success" : health?.overall === "warn" ? "warning" : "primary"}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="font-display">Assignment pipeline</CardTitle>
                <CardDescription>Claim and hardware-lock status across the license roster.</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MiniStat label="Claimed" value={claimed} />
                <MiniStat label="Reserved" value={reserved} />
                <MiniStat label="Unassigned" value={unassigned} />
                <MiniStat label="HW locked" value={hwLocked} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="font-display">Activation seats</CardTitle>
                <CardDescription>Devices activated vs maximum seats on listed licenses.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="font-display text-3xl font-semibold">{seatsUsed} <span className="text-lg text-muted-foreground">/ {seatsMax}</span></div>
                <p className="mt-2 text-sm text-muted-foreground">
                  Manage assignments on the Licenses page. Tenant sales detail lives under Reports.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button asChild size="sm" variant="outline"><Link to="/admin/licenses">Open licenses</Link></Button>
                  <Button asChild size="sm" variant="outline"><Link to="/admin/devices">Open devices</Link></Button>
                  <Button asChild size="sm" variant="outline"><Link to="/admin/system-health">System health</Link></Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="licenses" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">License summary</CardTitle>
              <CardDescription>
                {licensesQ.isLoading ? "Loading…" : `${licenses.length} license(s)`}
                {scope === "all" ? " · platform-wide" : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {licenses.length === 0 && !licensesQ.isLoading ? (
                <p className="text-sm text-muted-foreground">No licenses found.</p>
              ) : (
                licenses.slice(0, 40).map((row) => (
                  <div key={row.id || row.license_key} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/70 p-3 text-sm">
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs font-semibold">{row.license_key}</div>
                      <div className="text-xs text-muted-foreground">
                        {row.plan} · {row.activated_devices ?? 0}/{row.max_devices ?? 1} seats
                        {row.assigned_email ? ` · ${row.assigned_email}` : ""}
                        {row.org_id ? ` · org ${String(row.org_id).slice(0, 8)}…` : ""}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant="outline">{row.status || "—"}</Badge>
                      <Badge variant="secondary">{row.claim_status || "unassigned"}</Badge>
                    </div>
                  </div>
                ))
              )}
              {licenses.length > 40 ? (
                <p className="text-xs text-muted-foreground">Showing first 40. Full roster on Admin → Licenses.</p>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="devices" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Device summary</CardTitle>
              <CardDescription>
                {devicesQ.isLoading ? "Loading…" : `${devices.length} device(s) in current org context`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {devices.length === 0 && !devicesQ.isLoading ? (
                <p className="text-sm text-muted-foreground">No devices registered for this organization yet.</p>
              ) : (
                devices.slice(0, 40).map((d) => (
                  <div key={d.id || d.device_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/70 p-3 text-sm">
                    <div className="min-w-0">
                      <div className="font-medium">{d.computer_name || d.hostname || "Device"}</div>
                      <div className="truncate font-mono text-xs text-muted-foreground">{d.device_id}</div>
                      <div className="text-xs text-muted-foreground">
                        v{d.mbt_version || "—"} · last seen {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "never"}
                      </div>
                    </div>
                    <Badge variant={d.is_active === false ? "secondary" : "default"}>
                      {d.is_active === false ? "Offline" : "Online"}
                    </Badge>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sales" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Sales / analytics</CardTitle>
              <CardDescription>
                Org-scoped cloud analytics overview when sync data is available for the selected organization.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!orgId ? (
                <p className="text-sm text-muted-foreground">No organization context — open tenant Reports after selecting an org.</p>
              ) : analyticsQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading analytics…</p>
              ) : !analyticsOk ? (
                <p className="text-sm text-muted-foreground">
                  Analytics overview unavailable for this org (no synced sales yet, or endpoint returned an error).
                  Use the tenant Reports page for full sales, debts, and inventory panels.
                </p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <MiniStat label="Gross sales" value={Number.isFinite(gross) ? gross.toLocaleString() : "—"} />
                  <MiniStat label="Transactions" value={Number.isFinite(txns) ? txns.toLocaleString() : "—"} />
                </div>
              )}
              <Button asChild variant="outline">
                <Link to="/reports"><ExternalLink className="mr-1.5 h-4 w-4" />Open tenant Reports</Link>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 font-display text-xl font-semibold">{value}</div>
    </div>
  );
}
