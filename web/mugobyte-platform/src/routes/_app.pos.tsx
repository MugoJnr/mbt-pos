import { createFileRoute, Link } from "@tanstack/react-router";
import {
  BarChart3,
  Bell,
  CloudUpload,
  Download,
  KeyRound,
  LifeBuoy,
  MonitorSmartphone,
  Settings,
  Shield,
  Store,
  UserCircle2,
  Users,
  Building2,
  Bot,
  Activity,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { LiveOpsCallout } from "@/components/layout/LiveOpsCallout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export const Route = createFileRoute("/_app/pos")({
  component: PosHubPage,
  head: () => ({ meta: [{ title: "MBT POS Cloud | MugoByte" }] }),
});

const modules = [
  { title: "Reports", desc: "Daily, weekly, monthly cloud report history", url: "/reports", icon: BarChart3 },
  { title: "Devices", desc: "Installations, heartbeats, activation history", url: "/devices", icon: MonitorSmartphone },
  { title: "Licenses", desc: "Current seats, renew, transfer, invoices", url: "/license", icon: KeyRound },
  { title: "Backups", desc: "Cloud backup health and restore history", url: "/backups", icon: CloudUpload },
  { title: "Branches", desc: "Locations under your organization", url: "/branches", icon: Building2 },
  { title: "Users", desc: "Team access in the cloud account", url: "/users", icon: Users },
  { title: "Notifications", desc: "Inbox, categories and preferences", url: "/notifications", icon: Bell },
  { title: "Downloads", desc: "Desktop POS installers and release notes", url: "/downloads", icon: Download },
  { title: "Business Settings", desc: "Org profile and Live Dashboard URL", url: "/settings", icon: Settings },
  { title: "Security", desc: "Sessions and cloud audit", url: "/security", icon: Shield },
  { title: "AI Insights", desc: "Ask AI, forecasts and recommendations", url: "/ai", icon: Bot, badge: "Beta" },
  { title: "Support", desc: "Knowledge base and tickets", url: "/support", icon: LifeBuoy },
  { title: "Account", desc: "Your profile across the portal", url: "/account", icon: UserCircle2 },
  { title: "Cloud Health", desc: "Sync and platform status signals", url: "/devices", icon: Activity },
];

function PosHubPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="Product · MBT POS"
        title="MBT POS Cloud"
        description="Licenses, devices, backups and report history from Supabase / cloud APIs. Live shop and stock stay on your shop Live Dashboard."
        actions={
          <Button asChild variant="outline">
            <Link to="/dashboard">← Workspace home</Link>
          </Button>
        }
      />
      <LiveOpsCallout
        title="Open Live Dashboard"
        description="Real-time operations for this shop run on {shop}.mugobyte.com via Cloudflare — never mixed with Portal cloud analytics."
      />
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {modules.map((m) => (
          <Card key={`${m.url}-${m.title}`} className="transition hover:shadow-elegant">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <m.icon className="h-4 w-4 text-primary" />
                {m.title}
                {"badge" in m && m.badge ? (
                  <Badge variant="secondary" className="ml-auto text-[10px]">
                    {m.badge}
                  </Badge>
                ) : null}
              </CardTitle>
              <CardDescription>{m.desc}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild variant="outline" className="w-full">
                <Link to={m.url as "/reports"}>Open</Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
        <Store className="h-3.5 w-3.5" />
        Billing for seats and renewals will appear under Workspace → Billing.
      </p>
    </PageShell>
  );
}
