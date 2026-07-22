import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ShoppingCart,
  DollarSign,
  LineChart,
  AlertTriangle,
  Plus,
  Package,
  BarChart3,
  TrendingUp,
  Wallet,
  Landmark,
  Sparkles,
  HeartPulse,
  Activity,
  Banknote,
  Smartphone,
  Building2,
  RefreshCw,
  HardDrive,
  Users,
  FileText,
  Bell,
  Settings,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell, ThemeToggle } from "@/components/app-shell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  KpiCard,
  SectionTitle,
  Skeleton,
  Table,
} from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES, todayISO } from "@/lib/format";
import { loadPrefs, prefsRefreshMs, type DashboardPrefs } from "@/lib/prefs";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  component: Dashboard,
});

function HealthRing({ score, overall }: { score: number; overall: string }) {
  const color =
    overall === "healthy" ? "stroke-ok" : overall === "warn" ? "stroke-warn" : "stroke-err";
  return (
    <Link to="/health" className="relative h-16 w-16 shrink-0 block" title="Open System Health">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="40" fill="none" className="stroke-border" strokeWidth="10" />
        <circle
          cx="50"
          cy="50"
          r="40"
          fill="none"
          className={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${(score / 100) * 251} 251`}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-sm font-extrabold text-text tabular-nums">
        {score}
      </span>
    </Link>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 shadow-md text-xs">
      <div className="text-text2 mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="font-semibold text-gold tabular-nums">
          {KES(p.value)}
        </div>
      ))}
    </div>
  );
}

function can(perms: string[], ...need: string[]) {
  if (!perms.length) return true; // admin payloads may omit; UI still gated by API
  return need.some((n) => perms.includes(n));
}

function Dashboard() {
  const { user } = useAuth();
  const [prefs, setPrefs] = useState<DashboardPrefs>(() => loadPrefs());
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<DashboardPrefs>).detail;
      if (detail) setPrefs(detail);
      else setPrefs(loadPrefs());
    };
    window.addEventListener("mbt-prefs-changed", onChange);
    return () => window.removeEventListener("mbt-prefs-changed", onChange);
  }, []);

  const refreshMs = prefsRefreshMs(prefs);
  const today = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const [weekday, ...rest] = today.split(" ");
  const name = user?.full_name || user?.username || "Staff";
  const d = todayISO();
  const role = String(user?.role || "").toLowerCase();
  const isAdmin = ["admin", "superadmin", "manager"].includes(role);

  const summaryQ = useQuery({
    queryKey: ["reports-summary", d],
    queryFn: () => GET<any>("/reports/summary", { start: d, end: d }),
    refetchInterval: refreshMs,
  });
  const ccQ = useQuery({
    queryKey: ["cc-summary"],
    queryFn: () => GET<any>("/command-center/summary"),
    refetchInterval: refreshMs,
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<any>("/products"),
    refetchInterval: refreshMs * 1.5,
  });
  const salesQ = useQuery({
    queryKey: ["sales-today", d],
    queryFn: () => GET<any>("/sales", { start: d, end: d }),
    refetchInterval: refreshMs,
  });
  const insightsQ = useQuery({
    queryKey: ["ai-insights-dash"],
    queryFn: () => GET<any>("/ai/insights"),
    refetchInterval: Math.max(refreshMs, 90_000),
  });
  const healthQ = useQuery({
    queryKey: ["health-detail-dash"],
    queryFn: () => GET<any>("/health/detail"),
    refetchInterval: refreshMs,
  });
  const notifQ = useQuery({
    queryKey: ["notifications-dash"],
    queryFn: () => GET<any>("/notifications", { limit: "8" }),
    refetchInterval: prefs.notificationsEnabled ? refreshMs : false,
  });
  const liveQ = useQuery({
    queryKey: ["live-dash"],
    queryFn: () => GET<any>("/live"),
    refetchInterval: refreshMs,
  });

  const wrap = summaryQ.data || {};
  const s = wrap.summary || wrap;
  const cc = ccQ.data || {};
  const perms: string[] = Array.isArray(cc.permissions) ? cc.permissions : [];
  const products = Array.isArray(productsQ.data)
    ? productsQ.data
    : productsQ.data?.products || [];
  const sales = Array.isArray(salesQ.data) ? salesQ.data : salesQ.data?.sales || [];
  const lowStock =
    Number(cc.low_stock ?? 0) ||
    products.filter((p: any) => Number(p.stock || 0) <= Number(p.min_stock ?? 5)).length;

  const revenue = Number(cc.today?.revenue ?? s.total_revenue ?? 0);
  const txns = Number(cc.today?.transactions ?? s.total_transactions ?? sales.length ?? 0);
  const profit = Number(cc.today?.profit ?? 0);
  const monthRev = Number(cc.monthly_revenue ?? 0);
  const expenses = Number(cc.expenses ?? 0);
  const invValue = Number(cc.inventory_value ?? 0);
  const debts = Number(cc.outstanding_debts ?? 0);
  const cashFlow = Number(cc.cash_flow ?? revenue);
  const cash = Number(cc.today?.cash ?? 0);
  const mpesa = Number(cc.today?.mpesa ?? 0);
  const bank = Number(cc.today?.bank ?? 0);
  const businessHealth = Number(cc.business_health ?? healthQ.data?.score ?? 0);
  const topProducts = Array.isArray(cc.top_products) ? cc.top_products : [];
  const topCategories = Array.isArray(cc.top_categories) ? cc.top_categories : [];
  const bak = liveQ.data?.backup || {};
  const syncPending = Number(liveQ.data?.sync?.pending || 0);

  const healthScore = Number(healthQ.data?.score ?? 0);
  const healthOverall =
    healthQ.data?.overall ||
    (healthQ.isLoading
      ? "…"
      : businessHealth >= 70
        ? "healthy"
        : businessHealth >= 45
          ? "warn"
          : "err");
  const insights = insightsQ.data || {};
  const activity = Array.isArray(notifQ.data?.notifications)
    ? notifQ.data.notifications
    : [];

  const peakCashier = useMemo(() => {
    const list = Array.isArray(liveQ.data?.cashiers) ? liveQ.data.cashiers : [];
    return list[0] || null;
  }, [liveQ.data]);

  const hourly = useMemo(() => {
    const raw = Array.isArray(wrap.hourly) ? wrap.hourly : [];
    if (raw.length) {
      return raw.map((h: any) => ({
        hour: `${String(h.hour ?? h.label ?? "").padStart(2, "0")}:00`,
        total: Number(h.total || 0),
      }));
    }
    const buckets: Record<number, number> = {};
    for (let i = 0; i < 24; i++) buckets[i] = 0;
    for (const row of sales) {
      const t = row.created_at || row.sold_at || row.timestamp;
      if (!t) continue;
      const hr = new Date(t).getHours();
      if (!Number.isNaN(hr)) buckets[hr] += Number(row.total || 0);
    }
    const entries = Object.entries(buckets)
      .map(([h, total]) => ({ hour: `${String(h).padStart(2, "0")}:00`, total }))
      .filter((e) => e.total > 0);
    return entries.length
      ? entries
      : Object.entries(buckets)
          .slice(8, 20)
          .map(([h, total]) => ({ hour: `${String(h).padStart(2, "0")}:00`, total }));
  }, [wrap.hourly, sales]);

  const byPayment = useMemo(() => {
    const raw = Array.isArray(cc.by_payment)
      ? cc.by_payment
      : Array.isArray(wrap.by_payment)
        ? wrap.by_payment
        : [];
    if (raw.length) {
      return raw.map((p: any) => ({
        name: String(p.method || p.payment_method || p.name || "Other"),
        total: Number(p.total || 0),
      }));
    }
    const map: Record<string, number> = {};
    for (const row of sales) {
      const m = String(row.payment_method || "Cash");
      map[m] = (map[m] || 0) + Number(row.total || 0);
    }
    return Object.entries(map).map(([name, total]) => ({ name, total }));
  }, [cc.by_payment, wrap.by_payment, sales]);

  const peakHour = useMemo(() => {
    if (!hourly.length) return null;
    return hourly.reduce((a, b) => (b.total > a.total ? b : a), hourly[0]);
  }, [hourly]);

  const loading = summaryQ.isLoading && ccQ.isLoading;
  const dense = prefs.tableDensity === "compact" || prefs.layout === "dense";

  const quickActions = [
    { to: "/pos", label: "New Sale", icon: Plus, need: ["sales", "dashboard"], show: true },
    { to: "/inventory", label: "Inventory", icon: Package, need: ["inventory"], show: true },
    { to: "/debt", label: "Debts", icon: Landmark, need: ["debt"], show: true },
    { to: "/reports", label: "Reports", icon: FileText, need: ["reports"], show: true },
    { to: "/backup", label: "Backup", icon: HardDrive, need: ["backup", "settings"], show: isAdmin },
    { to: "/notifications", label: "Alerts", icon: Bell, need: ["dashboard"], show: true },
    { to: "/health", label: "Health", icon: HeartPulse, need: ["dashboard"], show: true },
    { to: "/settings", label: "Settings", icon: Settings, need: ["settings"], show: isAdmin },
    { to: "/live", label: "Refresh Live", icon: RefreshCw, need: ["dashboard"], show: true },
  ].filter((a) => a.show && (isAdmin || can(perms, ...a.need)));

  return (
    <AppShell title="Dashboard">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-5">
        <div className="min-w-0">
          <div className="text-xs text-text2">
            <span className="text-gold font-semibold">{weekday}</span>{" "}
            <span className="mx-1 text-muted-fg">·</span>
            <span>{rest.join(" ")}</span>
          </div>
          <h2 className="text-display text-text mt-1">How is business today?</h2>
          <div className="text-sm text-text2 mt-0.5">
            Welcome back, {name} · Live Dashboard · refreshes every {prefs.refreshIntervalSec}s
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {prefs.widgets.health ? (
            <div className="flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2 shadow-card">
              <HealthRing
                score={healthScore || businessHealth}
                overall={healthOverall}
              />
              <div className="leading-tight">
                <div className="text-eyebrow">System</div>
                <div className="text-sm font-semibold text-text capitalize">{healthOverall}</div>
                <div className="text-[11px] text-text2">
                  Biz score <span className="text-gold font-semibold">{businessHealth}</span>
                </div>
              </div>
            </div>
          ) : null}
          <ThemeToggle />
          <Link to="/pos">
            <Button variant="primary" size="touch">
              <Plus className="h-4 w-4" /> New Sale
            </Button>
          </Link>
        </div>
      </div>

      {/* Attention strip */}
      <div className="flex flex-wrap gap-2 mb-4">
        {lowStock > 0 ? (
          <Link to="/inventory">
            <Badge tone="warn">{lowStock} low stock — needs attention</Badge>
          </Link>
        ) : (
          <Badge tone="ok">Inventory healthy</Badge>
        )}
        {debts > 0 ? (
          <Link to="/debt">
            <Badge tone="warn">Outstanding credit {KES(debts)}</Badge>
          </Link>
        ) : (
          <Badge tone="ok">No open credit</Badge>
        )}
        {syncPending > 0 ? (
          <Badge tone="info">{syncPending} sync pending</Badge>
        ) : (
          <Badge tone="muted">Sync clear</Badge>
        )}
        <Badge tone={bak.status === "ok" ? "ok" : "warn"}>
          Backup {String(bak.status || "—").toUpperCase()}
        </Badge>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="p-4 space-y-3">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-3 w-16" />
            </Card>
          ))}
        </div>
      ) : (
        <>
          <div
            className={cn(
              "grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 mb-3",
              dense ? "sm:gap-3" : "sm:gap-4",
            )}
          >
            <KpiCard
              label="Today's Sales"
              value={KES(revenue)}
              sub={`${txns} transactions`}
              accent="gold"
              icon={<ShoppingCart className="h-5 w-5" />}
            />
            <KpiCard
              label="Today's Profit"
              value={KES(profit)}
              sub="From live cost data"
              accent="ok"
              icon={<DollarSign className="h-5 w-5" />}
            />
            <KpiCard
              label="Monthly Revenue"
              value={KES(monthRev)}
              sub="This calendar month"
              accent="info"
              icon={<LineChart className="h-5 w-5" />}
            />
            <KpiCard
              label="Low Stock"
              value={String(lowStock)}
              sub="Products at/below min"
              accent={lowStock ? "warn" : "ok"}
              icon={<AlertTriangle className="h-5 w-5" />}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
            <KpiCard
              label="Cash"
              value={KES(cash)}
              sub="Today"
              accent="ok"
              icon={<Banknote className="h-5 w-5" />}
            />
            <KpiCard
              label="M-Pesa"
              value={KES(mpesa)}
              sub="Today"
              accent="gold"
              icon={<Smartphone className="h-5 w-5" />}
            />
            <KpiCard
              label="Bank / Card"
              value={KES(bank)}
              sub="Today"
              accent="info"
              icon={<Building2 className="h-5 w-5" />}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <KpiCard
              label="Expenses"
              value={KES(expenses)}
              sub="Month (ledger)"
              accent="warn"
              icon={<Wallet className="h-5 w-5" />}
            />
            <KpiCard
              label="Inventory Value"
              value={KES(invValue)}
              sub={`${products.length} SKUs`}
              accent="info"
              icon={<Package className="h-5 w-5" />}
            />
            <KpiCard
              label="Pending Debts"
              value={KES(debts)}
              sub="Open invoices"
              accent={debts > 0 ? "warn" : "ok"}
              icon={<Landmark className="h-5 w-5" />}
            />
            <KpiCard
              label="Cash Flow"
              value={KES(cashFlow)}
              sub="Today proxy"
              accent="gold"
              icon={<TrendingUp className="h-5 w-5" />}
            />
          </div>
        </>
      )}

      {prefs.widgets.quickActions ? (
        <Card className="p-3 sm:p-4 mb-4">
          <SectionTitle>Quick actions</SectionTitle>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {quickActions.map((a) => {
              const Icon = a.icon;
              return (
                <Link
                  key={a.to + a.label}
                  to={a.to}
                  className="min-h-[48px] inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-panel/60 px-3 py-2.5 text-sm font-semibold text-text hover:bg-hover hover:border-gold/40 transition-ui"
                >
                  <Icon className="h-4 w-4 text-gold shrink-0" />
                  <span className="truncate">{a.label}</span>
                </Link>
              );
            })}
          </div>
        </Card>
      ) : null}

      {prefs.showCharts ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
          <Card className="p-4 lg:col-span-2">
            <SectionTitle
              action={
                <span className="text-xs text-text2">
                  {peakHour ? `Peak ${peakHour.hour}` : "Today · hourly"}
                </span>
              }
            >
              Revenue pulse
            </SectionTitle>
            <div className="h-[200px] w-full mt-1">
              {hourly.some((h) => h.total > 0) ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={hourly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="mbtGoldFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--gold)" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="var(--gold)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="hour"
                      tick={{ fill: "var(--text2)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fill: "var(--text2)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                      tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="total"
                      stroke="var(--gold)"
                      strokeWidth={2}
                      fill="url(#mbtGoldFill)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState
                  icon={<BarChart3 className="h-6 w-6" />}
                  title="No hourly data yet"
                  description="Sales today will populate this chart."
                  className="py-8"
                />
              )}
            </div>
          </Card>

          {prefs.widgets.paymentMix ? (
            <Card className="p-4">
              <SectionTitle>By payment</SectionTitle>
              <div className="h-[200px] w-full mt-1">
                {byPayment.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={byPayment} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="name"
                        tick={{ fill: "var(--text2)", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis hide />
                      <Tooltip content={<ChartTooltip />} />
                      <Bar dataKey="total" fill="var(--gold)" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <EmptyState title="No payments yet" className="py-8" />
                )}
              </div>
            </Card>
          ) : null}
        </div>
      ) : null}

      {prefs.showWidgets ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-4">
          {prefs.widgets.bestSellers ? (
            <Card className="p-4">
              <SectionTitle>Best sellers today</SectionTitle>
              {topProducts.length === 0 ? (
                <p className="text-sm text-text2 py-3">No product sales yet today.</p>
              ) : (
                <ul className="space-y-2">
                  {topProducts.slice(0, 6).map((p: any, i: number) => (
                    <li
                      key={p.name || i}
                      className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0"
                    >
                      <span className="text-sm font-medium text-text truncate">
                        {i + 1}. {p.name || p.product_name}
                      </span>
                      <span className="text-xs text-text2 tabular-nums shrink-0">
                        {p.qty || p.qty_sold || 0} ·{" "}
                        <span className="text-gold font-semibold">{KES(p.revenue)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : null}

          {prefs.widgets.topCategories ? (
            <Card className="p-4">
              <SectionTitle>Top categories</SectionTitle>
              {topCategories.length === 0 ? (
                <p className="text-sm text-text2 py-3">No category mix yet today.</p>
              ) : (
                <ul className="space-y-2">
                  {topCategories.slice(0, 6).map((c: any, i: number) => (
                    <li
                      key={c.name || i}
                      className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0"
                    >
                      <span className="text-sm font-medium text-text truncate">{c.name}</span>
                      <span className="text-gold font-semibold text-sm tabular-nums">
                        {KES(c.revenue)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : null}

          <Card className="p-4 border-gold/20 bg-gradient-to-b from-gold/[0.06] to-card">
            <SectionTitle
              action={
                <Link to="/ai" className="text-sm text-gold font-semibold inline-flex items-center gap-1">
                  <Sparkles className="h-3.5 w-3.5" /> AI
                </Link>
              }
            >
              Insights
            </SectionTitle>
            <p className="text-sm text-text mb-3 leading-relaxed">
              {insights.summary || "Loading insights from live SQLite…"}
            </p>
            <ul className="space-y-1.5 mb-3">
              {(insights.alerts || insights.recommendations || [])
                .slice(0, 4)
                .map((line: string, i: number) => (
                  <li
                    key={i}
                    className="text-xs text-text2 pl-2.5 border-l-2 border-gold/40 leading-snug"
                  >
                    {line}
                  </li>
                ))}
            </ul>
            <div className="text-[11px] text-text2 space-y-1">
              {peakCashier ? (
                <div className="flex items-center gap-1.5">
                  <Users className="h-3.5 w-3.5 text-gold" />
                  Top cashier:{" "}
                  <strong className="text-text">{peakCashier.name}</strong> (
                  {KES(peakCashier.revenue)})
                </div>
              ) : null}
              {peakHour ? (
                <div className="flex items-center gap-1.5">
                  <Activity className="h-3.5 w-3.5 text-gold" />
                  Peak hour: <strong className="text-text">{peakHour.hour}</strong>
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="lg:col-span-2 overflow-hidden">
          <div className="p-4 border-b border-border">
            <SectionTitle
              action={
                <Link to="/reports" className="text-sm text-gold font-semibold">
                  Reports
                </Link>
              }
            >
              Recent Sales
            </SectionTitle>
          </div>
          {sales.length === 0 ? (
            <EmptyState
              icon={<BarChart3 className="h-6 w-6" />}
              title="No sales yet today"
              description="Complete a sale on Point of Sale to see it here."
            />
          ) : (
            <>
              <div className="hidden sm:block">
                <Table head={["Receipt", "Total", "Pay", "Cashier"]}>
                  {sales.slice(0, dense ? 10 : 8).map((row: any) => (
                    <tr key={row.id || row.receipt_number}>
                      <td className={cn("px-4 font-mono text-text", dense ? "py-1.5" : "py-2.5")}>
                        {row.receipt_number || row.id}
                      </td>
                      <td
                        className={cn(
                          "px-4 tabular-nums font-semibold text-gold",
                          dense ? "py-1.5" : "py-2.5",
                        )}
                      >
                        {KES(row.total)}
                      </td>
                      <td className={cn("px-4 text-text2", dense ? "py-1.5" : "py-2.5")}>
                        {String(row.payment_method || "—")}
                      </td>
                      <td className={cn("px-4 text-text2", dense ? "py-1.5" : "py-2.5")}>
                        {String(row.cashier_name || "—")}
                      </td>
                    </tr>
                  ))}
                </Table>
              </div>
              <div className="sm:hidden divide-y divide-border">
                {sales.slice(0, 6).map((row: any) => (
                  <div key={row.id || row.receipt_number} className="px-4 py-3">
                    <div className="flex justify-between gap-2">
                      <span className="font-mono text-sm text-text">
                        {row.receipt_number || row.id}
                      </span>
                      <span className="font-bold text-gold tabular-nums">{KES(row.total)}</span>
                    </div>
                    <div className="text-xs text-text2 mt-0.5">
                      {row.payment_method || "—"} · {row.cashier_name || "—"}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>

        {prefs.widgets.activity ? (
          <Card className="p-4">
            <SectionTitle
              action={
                <Link to="/notifications" className="text-sm text-gold font-semibold">
                  All
                </Link>
              }
            >
              Recent Activity
            </SectionTitle>
            {activity.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-text2 py-4">
                <Activity className="h-4 w-4 text-gold" /> No recent events
              </div>
            ) : (
              <ul className="space-y-2">
                {activity.slice(0, 6).map((n: any) => (
                  <li
                    key={n.id}
                    className="flex items-start justify-between gap-2 py-1.5 border-b border-border/40 last:border-0"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-text truncate">{n.title}</div>
                      <div className="text-[11px] text-text2 truncate">{n.body}</div>
                    </div>
                    <Badge tone={n.severity === "warn" || n.severity === "err" ? "warn" : "muted"}>
                      {n.type}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <Link to="/live">
                <Button variant="secondary" size="touch">
                  <Activity className="h-4 w-4" /> Live
                </Button>
              </Link>
              <button
                type="button"
                className="md:hidden min-h-[44px] inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm font-semibold"
                onClick={() => window.dispatchEvent(new CustomEvent("mbt-open-search"))}
              >
                <Search className="h-4 w-4 text-gold" /> Search
              </button>
            </div>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
