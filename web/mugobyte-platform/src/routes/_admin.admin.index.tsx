import type { ComponentType } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Store, Users, KeyRound, MonitorSmartphone, Activity, ShieldCheck, TrendingUp,
  CloudUpload, Boxes, Database, Bell, Search,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { listCloudLicenses, listCloudDevices, GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_admin/admin/")({
  component: AdminDashboard,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function AdminDashboard() {
  const { orgId } = useAuth();
  const licensesQ = useQuery({
    queryKey: ["admin-home-licenses", orgId],
    queryFn: () => listCloudLicenses(orgId),
  });
  const devicesQ = useQuery({
    queryKey: ["admin-home-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
  });
  const healthQ = useQuery({
    queryKey: ["admin-home-health"],
    queryFn: () => GET<{ score?: number; overall?: string }>("/health/detail"),
    retry: 1,
  });

  const licenses = licensesQ.data?.licenses || [];
  const devices = devicesQ.data?.devices || [];
  const activeLic = licenses.filter((l) => {
    const s = (l.status || "").toLowerCase();
    return s === "active" || s === "trial";
  }).length;
  const onlineDevices = devices.filter((d) => d.is_active !== false).length;
  const orgHint = licensesQ.data?.scope === "all"
    ? `${new Set(licenses.map((l) => l.org_id).filter(Boolean)).size || "—"} orgs in license roster`
    : "Current org context";

  return (
    <PageShell>
      <PageHeader
        eyebrow="Platform Admin"
        title="MugoByte Platform overview"
        description="Shared control plane for users, organizations, applications, devices, licenses and audit history."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/reports">Reports Center</Link>
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="License orgs"
          value={licensesQ.isLoading ? "…" : String(new Set(licenses.map((l) => l.org_id).filter(Boolean)).size || (orgId ? 1 : 0))}
          icon={Store}
          hint={orgHint}
          accent="primary"
        />
        <StatCard
          label="Active licenses"
          value={licensesQ.isLoading ? "…" : String(activeLic)}
          icon={KeyRound}
          hint={`${licenses.length} total`}
          accent="success"
        />
        <StatCard
          label="Online devices"
          value={devicesQ.isLoading ? "…" : String(onlineDevices)}
          icon={MonitorSmartphone}
          hint={`${devices.length} registered`}
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
            <CardTitle className="font-display">Platform services</CardTitle>
            <CardDescription>Core shared services required by the architecture spec.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[
              [ShieldCheck, "Authentication", "Central sign-in, sessions, verification and MFA-ready flows."],
              [Boxes, "Applications", "Launcher, app registry and future marketplace enablement."],
              [Bell, "Notifications", "Cross-product alerts with filtering by application."],
              [Database, "Storage & backups", "Cloud backup visibility and storage controls."],
              [Search, "Global search", "Applications, organizations, users and settings."],
              [CloudUpload, "Audit & health", "Operational history, health surfaces and exportability."],
            ].map(([Icon, title, desc]) => (
              <div key={title as string} className="rounded-xl border border-border/70 p-4">
                <Icon className="h-5 w-5 text-primary" />
                <div className="mt-3 font-medium">{title as string}</div>
                <p className="mt-1 text-sm text-muted-foreground">{desc as string}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-display">Readiness</CardTitle>
            <CardDescription>Executive view of platform adoption.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ReadinessRow icon={TrendingUp} label="MBT POS" value="Integrated" tone="default" />
            <ReadinessRow icon={ShieldCheck} label="Shared auth" value="Live backend login" tone="default" />
            <ReadinessRow icon={CloudUpload} label="Reports export" value="Connected" tone="default" />
            <ReadinessRow icon={Activity} label="Cloud sync" value="In progress" tone="secondary" />
            <ReadinessRow icon={KeyRound} label="Central licensing" value="Assign + claim live" tone="default" />
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

function ReadinessRow({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string;
  tone: "default" | "secondary" | "destructive" | "outline";
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/70 p-3">
      <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{value}</div>
      </div>
      <Badge variant={tone}>{value}</Badge>
    </div>
  );
}
