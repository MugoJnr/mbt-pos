import type { ComponentType } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Store, Users, KeyRound, MonitorSmartphone, Activity, ShieldCheck, TrendingUp, CloudUpload, Boxes, Database, Bell, Search } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export const Route = createFileRoute("/_admin/admin/")({
  component: AdminDashboard,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function AdminDashboard() {
  return (
    <PageShell>
      <PageHeader eyebrow="Platform Admin" title="MugoByte Platform overview" description="Shared control plane for users, organizations, applications, devices, licenses and audit history." />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Organizations" value="—" icon={Store} hint="Connect live APIs for counts" accent="primary" />
        <StatCard label="Active licenses" value="—" icon={KeyRound} hint="From license roster" accent="success" />
        <StatCard label="Online devices" value="—" icon={MonitorSmartphone} hint="From device roster" accent="info" />
        <StatCard label="Platform users" value="—" icon={Users} hint="From memberships" accent="warning" />
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
          <CardHeader><CardTitle className="font-display">Readiness</CardTitle><CardDescription>Executive view of platform adoption.</CardDescription></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ReadinessRow icon={TrendingUp} label="MBT POS" value="Integrated" tone="default" />
            <ReadinessRow icon={ShieldCheck} label="Shared auth" value="Live backend login" tone="default" />
            <ReadinessRow icon={CloudUpload} label="Reports export" value="Connected" tone="default" />
            <ReadinessRow icon={Activity} label="Cloud sync" value="In progress" tone="secondary" />
            <ReadinessRow icon={KeyRound} label="Central licensing" value="Visibility live" tone="secondary" />
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

function ReadinessRow({ icon: Icon, label, value, tone }: { icon: ComponentType<{ className?: string }>; label: string; value: string; tone: "default" | "secondary" | "destructive" | "outline" }) {
  return <div className="flex items-center gap-3 rounded-xl border border-border/70 p-3"><div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></div><div className="min-w-0 flex-1"><div className="font-medium">{label}</div><div className="text-xs text-muted-foreground">{value}</div></div><Badge variant={tone}>{value}</Badge></div>;
}
