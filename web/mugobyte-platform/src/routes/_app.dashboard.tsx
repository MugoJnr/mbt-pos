import React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BarChart3,
  Bell,
  Boxes,
  Building2,
  CloudUpload,
  ExternalLink,
  KeyRound,
  LayoutGrid,
  MonitorSmartphone,
  Radio,
  ShieldCheck,
  Sparkles,
  Store,
  Download,
  Activity,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { canLaunch, fetchApplications, fetchOrganizations, type PlatformApp } from "@/lib/platform";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/_app/dashboard")({
  component: WorkspaceHome,
  head: () => ({ meta: [{ title: "MugoByte Workspace | MugoByte" }] }),
});

function iconForApp(id: string) {
  if (id.includes("pos")) return Store;
  if (id.includes("exam") || id.includes("school")) return Building2;
  if (id.includes("analytics") || id.includes("ai")) return BarChart3;
  if (id.includes("farm") || id.includes("agriculture")) return Sparkles;
  return Boxes;
}

function displayName(user: { full_name?: string; name?: string; username?: string; email?: string } | null) {
  if (!user) return "there";
  return (
    user.full_name ||
    user.name ||
    user.username ||
    (user.email || "").split("@")[0] ||
    "there"
  );
}

function WorkspaceHome() {
  const { orgId, setActiveOrg, user } = useAuth();
  const orgsQ = useQuery({ queryKey: ["platform-orgs"], queryFn: fetchOrganizations });
  const orgs = orgsQ.data || [];
  const activeOrg = orgs.find((o) => o.id === orgId) || orgs[0];

  useEffect(() => {
    if (!orgId && orgs[0]) setActiveOrg(orgs[0].id);
  }, [orgId, orgs, setActiveOrg]);

  const appsQ = useQuery({
    queryKey: ["platform-apps", activeOrg?.id || "default"],
    queryFn: () => fetchApplications(activeOrg?.id),
  });
  const apps = appsQ.data || [];

  const devicesQ = useQuery({
    queryKey: ["workspace-devices", orgId],
    queryFn: () =>
      GET<{ devices?: Array<{ computer_name?: string; status?: string; last_seen?: string }> }>(
        "/cloud/devices",
        orgId ? { org_id: orgId } : undefined,
      ),
    retry: false,
  });
  const devices = devicesQ.data?.devices || [];

  const notifQ = useQuery({
    queryKey: ["workspace-notifs", orgId],
    queryFn: () =>
      GET<{ notifications?: Array<{ title: string; created_at?: string; severity?: string }>; unread?: number }>(
        "/cloud/v1/notifications",
        orgId ? { org_id: orgId } : undefined,
      ),
    retry: false,
  });
  const notifs = (notifQ.data?.notifications || []).slice(0, 4);
  const unread = notifQ.data?.unread ?? 0;

  const liveUrl =
    (typeof window !== "undefined" && localStorage.getItem("mbt_live_dashboard_url")) || "";

  const name = displayName(user as { full_name?: string; username?: string; email?: string } | null);

  return (
    <PageShell>
      <PageHeader
        eyebrow="MugoByte Workspace"
        title={`Welcome back, ${name}.`}
        description="One account for every MugoByte product. Cloud tools live here — live shop operations stay on your shop Live Dashboard."
        actions={
          <div className="flex flex-wrap gap-2">
            {liveUrl ? (
              <Button asChild variant="outline">
                <a href={liveUrl} target="_blank" rel="noreferrer">
                  <Radio className="mr-1.5 h-4 w-4 text-emerald-500" />
                  Open Live Shop
                  <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
                </a>
              </Button>
            ) : null}
            <Button asChild>
              <Link to="/pos">
                <Store className="mr-1.5 h-4 w-4" />
                MBT POS Cloud
              </Link>
            </Button>
          </div>
        }
      />

      {/* Quick strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Products", value: String(apps.length), icon: LayoutGrid, hint: "In your workspace" },
          { label: "Businesses", value: String(orgs.length), icon: Building2, hint: "Switch anytime" },
          { label: "Devices", value: String(devices.length || "—"), icon: MonitorSmartphone, hint: "Registered installs" },
          { label: "Unread", value: String(unread), icon: Bell, hint: "Notifications" },
        ].map((s) => (
          <Card key={s.label} className="border-border/70 bg-card/60">
            <CardContent className="flex items-center gap-3 p-4">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                <s.icon className="h-5 w-5" />
              </div>
              <div>
                <div className="text-2xl font-semibold tracking-tight">{s.value}</div>
                <div className="text-xs text-muted-foreground">{s.label} · {s.hint}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.65fr_1fr]">
        {/* Left column */}
        <div className="space-y-4">
          {/* My Products — centerpiece */}
          <Card id="products" className="overflow-hidden">
            <CardHeader className="border-b border-border/60 bg-muted/20">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="font-display text-xl">My Products</CardTitle>
                  <CardDescription>
                    Launch apps for {activeOrg?.name || "your organization"}. Designed for unlimited future MugoByte products.
                  </CardDescription>
                </div>
                <Badge variant="secondary">{apps.filter((a) => a.status === "active").length} active</Badge>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
              {apps.map((app) => (
                <ProductCard key={app.id} app={app} />
              ))}
            </CardContent>
          </Card>

          {/* Quick actions */}
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Quick actions</CardTitle>
              <CardDescription>Common cloud tasks for the selected business.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { to: "/reports", icon: BarChart3, label: "Reports" },
                { to: "/license", icon: KeyRound, label: "Licenses" },
                { to: "/devices", icon: MonitorSmartphone, label: "Devices" },
                { to: "/backups", icon: CloudUpload, label: "Backups" },
                { to: "/downloads", icon: Download, label: "Downloads" },
                { to: "/notifications", icon: Bell, label: "Inbox" },
                { to: "/settings", icon: ShieldCheck, label: "Settings" },
                { to: "/ai", icon: Sparkles, label: "AI Hub" },
              ].map((a) => (
                <Button key={a.to} asChild variant="outline" className="h-auto justify-start gap-2 py-3">
                  <Link to={a.to}>
                    <a.icon className="h-4 w-4 text-primary" />
                    {a.label}
                  </Link>
                </Button>
              ))}
            </CardContent>
          </Card>
        </div>

        {/* Right rail */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">My businesses</CardTitle>
              <CardDescription>Switch context — cloud data follows the selection.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {orgs.map((org) => (
                <button
                  key={org.id}
                  type="button"
                  onClick={() => setActiveOrg(org.id)}
                  className={`w-full rounded-xl border p-3 text-left transition ${
                    activeOrg?.id === org.id
                      ? "border-primary bg-primary/5 shadow-sm"
                      : "border-border bg-background hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{org.name}</div>
                      <div className="text-xs text-muted-foreground">{org.role || "member"}</div>
                    </div>
                    {org.is_primary ? <Badge variant="secondary">Primary</Badge> : null}
                    {activeOrg?.id === org.id ? <Badge>Active</Badge> : null}
                  </div>
                </button>
              ))}
              <Button asChild variant="ghost" className="w-full">
                <Link to="/businesses">Manage businesses</Link>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Notifications</CardTitle>
              <CardDescription>Latest cloud alerts.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {notifs.length === 0 ? (
                <p className="text-sm text-muted-foreground">No notifications yet.</p>
              ) : (
                notifs.map((n, i) => (
                  <div key={i} className="rounded-lg border border-border/60 px-3 py-2">
                    <div className="text-sm font-medium">{n.title}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {(n.created_at || "").toString().slice(0, 16)} · {n.severity || "info"}
                    </div>
                  </div>
                ))
              )}
              <Button asChild variant="outline" size="sm" className="w-full">
                <Link to="/notifications">Open inbox</Link>
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 font-display">
                <Activity className="h-4 w-4" /> Connected devices
              </CardTitle>
              <CardDescription>Installs registered to this business.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {devices.length === 0 ? (
                <p className="text-sm text-muted-foreground">No devices synced yet. Activate from Desktop POS.</p>
              ) : (
                devices.slice(0, 5).map((d, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-sm">
                    <span className="truncate font-medium">{d.computer_name || "Device"}</span>
                    <Badge variant="outline">{d.status || "unknown"}</Badge>
                  </div>
                ))
              )}
              <Button asChild variant="outline" size="sm" className="w-full">
                <Link to="/devices">Device center</Link>
              </Button>
            </CardContent>
          </Card>

          <Card className="border-emerald-500/25 bg-emerald-500/5">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Radio className="h-4 w-4 text-emerald-500" /> Live Shop
              </CardTitle>
              <CardDescription>
                Real-time till, stock and cashier status live on your Cloudflare tunnel — never mixed with cloud analytics.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {liveUrl ? (
                <Button asChild className="w-full">
                  <a href={liveUrl} target="_blank" rel="noreferrer">
                    Open Live Dashboard <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
                  </a>
                </Button>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Set your shop URL in Settings (e.g. https://your-shop.mugobyte.com) to enable one-click Live Dashboard.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </PageShell>
  );
}

function ProductCard({ app }: { app: PlatformApp }) {
  const Icon = iconForApp(app.id);
  const launchable = canLaunch(app);
  return (
    <div className="group flex flex-col rounded-2xl border border-border/70 bg-background/70 p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-elegant">
      <div className="flex items-start justify-between gap-2">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary transition group-hover:bg-primary/15">
          <Icon className="h-5 w-5" />
        </div>
        <Badge
          variant={app.status === "active" ? "default" : app.status === "read_only" ? "secondary" : "outline"}
          className="capitalize"
        >
          {app.status.replace(/_/g, " ")}
        </Badge>
      </div>
      <h3 className="mt-3 font-display text-base font-semibold">{app.name}</h3>
      <p className="mt-1.5 min-h-10 flex-1 text-xs leading-relaxed text-muted-foreground">{app.description}</p>
      <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>{app.category}</span>
        <span>{app.version || "—"}</span>
      </div>
      <div className="mt-3">
        {launchable ? (
          <Button asChild className="w-full" size="sm">
            <Link to={(app.launch_url || "/pos") as "/pos"}>
              Launch <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
            </Link>
          </Button>
        ) : (
          <Button disabled className="w-full" size="sm" variant="secondary">
            Coming soon
          </Button>
        )}
      </div>
    </div>
  );
}
