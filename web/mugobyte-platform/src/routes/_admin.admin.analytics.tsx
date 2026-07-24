import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, RefreshCw, ExternalLink, KeyRound, MonitorSmartphone } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { listCloudLicenses, listCloudDevices, GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_admin/admin/analytics")({
  component: AdminAnalyticsPage,
  head: () => ({ meta: [{ title: "Admin Analytics | MugoByte" }] }),
});

function AdminAnalyticsPage() {
  const { orgId } = useAuth();
  const licensesQ = useQuery({
    queryKey: ["admin-analytics-licenses", orgId],
    queryFn: () => listCloudLicenses(orgId),
  });
  const devicesQ = useQuery({
    queryKey: ["admin-analytics-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
  });
  const analyticsQ = useQuery({
    queryKey: ["admin-analytics-overview", orgId],
    queryFn: () => {
      const end = new Date();
      const start = new Date();
      start.setDate(end.getDate() - 29);
      const iso = (d: Date) => d.toISOString().slice(0, 10);
      return GET<Record<string, unknown>>("/cloud/analytics/overview", {
        org_id: orgId,
        start: iso(start),
        end: iso(end),
      });
    },
    enabled: Boolean(orgId),
    retry: 0,
  });

  const licenses = licensesQ.data?.licenses || [];
  const devices = devicesQ.data?.devices || [];
  const summary = (analyticsQ.data?.summary || analyticsQ.data?.kpis || analyticsQ.data || {}) as Record<string, unknown>;
  const claimed = licenses.filter((l) => (l.claim_status || "").toLowerCase() === "claimed").length;
  const activeDevices = devices.filter((d) => d.is_active !== false).length;
  const gross = Number(summary.gross_sales ?? summary.sales_total ?? summary.revenue ?? NaN);
  const analyticsOk = !analyticsQ.isError && analyticsQ.data && !analyticsQ.data.error;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Analytics"
        description="Platform adoption signals and a shortcut into org sales analytics."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              void licensesQ.refetch();
              void devicesQ.refetch();
              if (orgId) void analyticsQ.refetch();
            }}
          >
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Licenses" value={String(licenses.length)} icon={KeyRound} hint={licensesQ.data?.scope === "all" ? "All orgs" : "Current org"} accent="primary" />
        <StatCard label="Claimed" value={String(claimed)} icon={TrendingUp} hint="Assignment claimed" accent="success" />
        <StatCard label="Devices" value={String(devices.length)} icon={MonitorSmartphone} hint={`${activeDevices} active`} accent="info" />
        <StatCard
          label="Gross sales"
          value={analyticsOk && Number.isFinite(gross) ? gross.toLocaleString() : "—"}
          icon={TrendingUp}
          hint={orgId ? (analyticsOk ? "Org overview" : "No synced sales") : "Select an org"}
          accent="warning"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="font-display">Where to dig deeper</CardTitle>
          <CardDescription>
            Cohort and retention views are not wired yet. Use Reports Center for license/device rollups and tenant Reports for sales detail.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild variant="outline"><Link to="/admin/reports">Reports Center</Link></Button>
          <Button asChild variant="outline"><Link to="/reports"><ExternalLink className="mr-1.5 h-4 w-4" />Tenant Reports</Link></Button>
          <Button asChild variant="outline"><Link to="/admin/licenses">Licenses</Link></Button>
        </CardContent>
      </Card>
    </PageShell>
  );
}
