import React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  AlertCircle,
  BarChart3,
  Bell,
  Boxes,
  Building2,
  CloudUpload,
  ExternalLink,
  KeyRound,
  LayoutGrid,
  Loader2,
  MonitorSmartphone,
  Radio,
  ShieldCheck,
  Sparkles,
  Store,
  Download,
  Activity,
  Banknote,
  ChevronDown,
  Receipt,
  WalletCards,
} from "lucide-react";
import { PageShell, PageHeader, EmptyState } from "@/components/layout/PageShell";
import { StatCard } from "@/components/layout/StatCard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import {
  canLaunch,
  fetchApplications,
  fetchOrganizations,
  groupAppsBySection,
  type PlatformApp,
} from "@/lib/platform";
import { GET } from "@/lib/api";
import {
  type AnalyticsResponse,
  daysAgoIso,
  formatCompactMoney,
  formatDateTime,
  formatNumber,
  todayIso,
  value,
} from "@/components/reports/analytics";

export const Route = createFileRoute("/_app/dashboard")({
  component: WorkspaceHome,
  head: () => ({ meta: [{ title: "MugoByte Workspace | MugoByte" }] }),
});

function iconForApp(id: string) {
  if (id === "pulse" || id.includes("pulse")) return Activity;
  if (id.includes("pos")) return Store;
  if (id.includes("exam") || id.includes("school")) return Building2;
  if (id.includes("analytics") || id.includes("ai")) return BarChart3;
  if (id.includes("farm") || id.includes("agriculture")) return Sparkles;
  return Boxes;
}

function displayName(user: {
  full_name?: string;
  name?: string;
  username?: string;
  email?: string;
} | null) {
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
  // Home KPIs: last 30 local days (Reports page keeps today-only default).
  const rangeStart = daysAgoIso(30);
  const rangeEnd = todayIso();

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
    enabled: Boolean(orgId),
  });
  const devices = devicesQ.data?.devices || [];

  const notifQ = useQuery({
    queryKey: ["workspace-notifs", orgId],
    queryFn: () =>
      GET<{
        notifications?: Array<{ title: string; created_at?: string; severity?: string }>;
        unread?: number;
      }>("/cloud/v1/notifications", orgId ? { org_id: orgId } : undefined),
    retry: false,
    enabled: Boolean(orgId),
  });
  const notifs = (notifQ.data?.notifications || []).slice(0, 4);
  const unread = notifQ.data?.unread ?? 0;

  const analyticsQ = useQuery({
    queryKey: ["dashboard-overview", orgId, rangeStart, rangeEnd],
    queryFn: () =>
      GET<AnalyticsResponse>("/cloud/analytics/overview", {
        org_id: orgId,
        start: rangeStart,
        end: rangeEnd,
      }),
    enabled: Boolean(orgId),
    retry: false,
  });
  const overview = analyticsQ.data || {};
  const summary = (overview.summary || overview.kpis || overview.data || overview) as Record<
    string,
    unknown
  >;
  const currency = String(overview.currency || summary.currency || "KES");
  const gross = Number(value(summary, "gross_sales", "sales_total", "revenue") ?? 0);
  const collected = Number(
    value(summary, "collected_revenue", "collected", "cash_collected") ?? 0,
  );
  const outstanding = Number(
    value(summary, "debt_outstanding", "outstanding_debt", "balance") ?? 0,
  );
  const transactions = Number(
    value(summary, "transactions", "sales_count", "receipts") ?? 0,
  );
  const lastSync =
    value(summary, "last_sync_at", "last_sync") ||
    overview.last_sync_at ||
    null;

  const liveUrl =
    (typeof window !== "undefined" && localStorage.getItem("mbt_live_dashboard_url")) || "";

  const name = displayName(user as { full_name?: string; username?: string; email?: string } | null);

  return (
    <PageShell>
      <PageHeader
        eyebrow="MugoByte · Workspace"
        title={`Welcome back, ${name}.`}
        description="Same MugoByte account as MBT POS desktop — cloud licenses, devices, and synced reports live here; till ops stay on the shop Live Dashboard."
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

      <Card className="overflow-hidden border-primary/20 bg-gradient-to-br from-primary/5 via-background to-info/5">
        <CardHeader className="flex flex-col gap-3 border-b border-border/50 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="font-display text-xl">Cloud performance</CardTitle>
            <CardDescription>
              Synced cloud analytics for {activeOrg?.name || "your business"} ·{" "}
              {lastSync ? `Last sync ${formatDateTime(lastSync)}` : "Waiting for first sync"}
            </CardDescription>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/reports">
              <BarChart3 className="mr-1.5 h-4 w-4" />
              Open reports
            </Link>
          </Button>
        </CardHeader>
        <CardContent className="p-4 sm:p-5">
          {!orgId ? (
            <p className="text-sm text-muted-foreground">Select a business to load synced KPIs.</p>
          ) : analyticsQ.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" role="status" aria-live="polite">
              {(
                [
                  { label: "Gross sales", icon: Receipt },
                  { label: "Collected", icon: Banknote },
                  { label: "Outstanding debt", icon: WalletCards },
                  { label: "Transactions", icon: Activity },
                ] as const
              ).map(({ label, icon: Icon }) => (
                <div
                  key={label}
                  className="rounded-xl border border-border/60 bg-muted/20 p-4"
                >
                  <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </div>
                  <div className="mt-3 h-7 w-28 animate-pulse rounded-md bg-muted/50" />
                  <p className="mt-2 text-[10px] text-muted-foreground/80">Loading cloud KPIs…</p>
                </div>
              ))}
              <span className="sr-only">Loading cloud analytics…</span>
            </div>
          ) : analyticsQ.isError || overview.error ? (
            <div className="flex min-h-28 flex-col items-center justify-center gap-2 text-center" role="alert">
              <AlertCircle className="h-5 w-5 text-destructive" />
              <p className="text-sm font-medium">Couldn’t load cloud analytics</p>
              <p className="text-xs text-muted-foreground">
                {String(overview.error || (analyticsQ.error as Error)?.message || "Request failed")}
              </p>
              <Button size="sm" variant="outline" onClick={() => void analyticsQ.refetch()}>
                Try again
              </Button>
            </div>
          ) : !lastSync && gross === 0 && collected === 0 && outstanding === 0 && transactions === 0 ? (
            <div className="flex min-h-28 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-primary/30 bg-primary/[0.04] px-4 py-7 text-center">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/15">
                <CloudUpload className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">Waiting for first shop sync</p>
                <p className="mt-1.5 max-w-md text-xs leading-relaxed text-muted-foreground">
                  Cloud KPIs stay at zero until a licensed POS install syncs sales for{" "}
                  {activeOrg?.name || "this business"}. Activate a license or open Live Shop to start.
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                <Button asChild size="sm">
                  <Link to="/license">
                    <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                    Activate license
                  </Link>
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link to="/reports">
                    <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
                    Open reports
                  </Link>
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard
                label="Gross sales"
                value={formatCompactMoney(gross, currency)}
                icon={Receipt}
                hint="Last 30 days · cloud"
                accent="primary"
              />
              <StatCard
                label="Collected"
                value={formatCompactMoney(collected, currency)}
                icon={Banknote}
                hint="Sales + debt payments"
                accent="success"
              />
              <StatCard
                label="Outstanding debt"
                value={formatCompactMoney(outstanding, currency)}
                icon={WalletCards}
                hint="Open balances"
                accent="warning"
              />
              <StatCard
                label="Transactions"
                value={formatNumber(transactions)}
                icon={Activity}
                hint="Active receipts"
                accent="info"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          {
            label: "Products",
            value: appsQ.isLoading ? "…" : appsQ.isError ? "—" : String(apps.length),
            icon: LayoutGrid,
            hint: appsQ.isError ? "Couldn’t load" : "In your workspace",
          },
          {
            label: "Businesses",
            value: orgsQ.isLoading ? "…" : orgsQ.isError ? "—" : String(orgs.length),
            icon: Building2,
            hint: orgsQ.isError ? "Couldn’t load" : "Switch anytime",
          },
          {
            label: "Devices",
            value: devicesQ.isLoading
              ? "0"
              : devicesQ.isError
                ? "—"
                : String(devices.length || "0"),
            icon: MonitorSmartphone,
            hint: devicesQ.isError ? "Couldn’t load" : "Registered installs",
          },
          {
            label: "Unread",
            value: notifQ.isLoading ? "…" : notifQ.isError ? "—" : String(unread),
            icon: Bell,
            hint: notifQ.isError ? "Couldn’t load" : "Notifications",
          },
        ].map((s) => (
          <Card key={s.label} className="border-border/70 bg-card/60">
            <CardContent className="flex items-center gap-3 p-4">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                <s.icon className="h-5 w-5" />
              </div>
              <div>
                <div className="text-2xl font-semibold tracking-tight">{s.value}</div>
                <div className="text-xs text-muted-foreground">
                  {s.label} · {s.hint}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.65fr_1fr]">
        <div className="space-y-4">
          <Card id="products" className="relative overflow-hidden shadow-[0_12px_40px_-24px_rgba(0,0,0,0.45)]">
            <CardHeader className="border-b border-border/60 bg-muted/20">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="font-display text-xl">My Products</CardTitle>
                  <CardDescription>
                    Launch apps for {activeOrg?.name || "your organization"}. Designed for unlimited
                    future MugoByte products.
                  </CardDescription>
                </div>
                <Badge variant="secondary">
                  {apps.filter((a) => a.status === "active").length} active
                </Badge>
              </div>
              <div className="mt-3 flex items-center justify-center gap-1.5 rounded-full border border-border/70 bg-background/80 px-3 py-1.5 text-[11px] font-medium text-muted-foreground shadow-sm">
                <ChevronDown className="h-3.5 w-3.5 animate-bounce" aria-hidden />
                Scroll for more products below
                <ChevronDown className="h-3.5 w-3.5 animate-bounce" aria-hidden />
              </div>
            </CardHeader>
            <CardContent className="relative max-h-[28rem] space-y-6 overflow-y-auto p-4 pb-14">
              {appsQ.isLoading ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Loading products…</p>
              ) : appsQ.isError ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Products could not be loaded.
                </p>
              ) : apps.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  No products in this workspace yet.
                </p>
              ) : (
                groupAppsBySection(apps).map((group) => (
                  <section key={group.section} className="space-y-3">
                    <div className="flex items-end justify-between gap-3 border-b border-border/60 pb-2">
                      <div>
                        <h3 className="font-display text-sm font-semibold tracking-tight">
                          {group.section}
                        </h3>
                        <p className="text-[11px] text-muted-foreground">
                          {group.apps.length} product{group.apps.length === 1 ? "" : "s"}
                        </p>
                      </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      {group.apps.map((app) => (
                        <ProductCard key={app.id} app={app} />
                      ))}
                    </div>
                  </section>
                ))
              )}
              <div
                className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-background via-background/85 to-transparent"
                aria-hidden
              />
              <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
                <span className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-background/90 px-3 py-1 text-[11px] font-medium text-muted-foreground shadow-sm backdrop-blur-sm">
                  Continue scrolling
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                </span>
              </div>
            </CardContent>
          </Card>

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
                <Button
                  key={a.to}
                  asChild
                  variant="outline"
                  className="h-auto min-h-11 justify-start gap-2 py-3"
                >
                  <Link to={a.to}>
                    <a.icon className="h-4 w-4 text-primary" />
                    {a.label}
                  </Link>
                </Button>
              ))}
            </CardContent>
          </Card>
        </div>

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
              {notifQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : notifQ.isError ? (
                <p className="text-sm text-muted-foreground">Notifications unavailable.</p>
              ) : notifs.length === 0 ? (
                <EmptyState
                  icon={Bell}
                  title="No notifications yet"
                  description="Cloud alerts for licenses, devices, and backups will appear here."
                  compact
                />
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
              {devicesQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : devicesQ.isError ? (
                <p className="text-sm text-muted-foreground">Devices unavailable.</p>
              ) : devices.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No devices synced yet. Activate from Desktop POS.
                </p>
              ) : (
                devices.slice(0, 5).map((d, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2 text-sm"
                  >
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
                Real-time till, stock and cashier status live on your Cloudflare tunnel — never mixed
                with cloud analytics.
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
                  Set your shop URL in Settings (e.g. https://your-shop.mugobyte.com) to enable
                  one-click Live Dashboard.
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
          variant={
            app.status === "active" ? "default" : app.status === "read_only" ? "secondary" : "outline"
          }
          className="capitalize"
        >
          {app.status.replace(/_/g, " ")}
        </Badge>
      </div>
      <h3 className="mt-3 font-display text-base font-semibold">{app.name}</h3>
      <p className="mt-1.5 min-h-10 flex-1 text-xs leading-relaxed text-muted-foreground">
        {app.description}
      </p>
      <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>{app.section || app.category}</span>
        <span>{app.version || "—"}</span>
      </div>
      {app.company ? (
        <p className="mt-1 text-[10px] text-muted-foreground/80">{app.company}</p>
      ) : null}
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
