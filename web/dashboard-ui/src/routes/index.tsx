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
} from "lucide-react";
import { useMemo } from "react";
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

function Dashboard() {
  const { user } = useAuth();
  const today = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const [weekday, ...rest] = today.split(" ");
  const name = user?.full_name || user?.username || "Staff";
  const d = todayISO();

  const summaryQ = useQuery({
    queryKey: ["reports-summary", d],
    queryFn: () => GET<any>("/reports/summary", { start: d, end: d }),
    refetchInterval: 60_000,
  });
  const ccQ = useQuery({
    queryKey: ["cc-summary"],
    queryFn: () => GET<any>("/command-center/summary"),
    refetchInterval: 60_000,
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<any>("/products"),
    refetchInterval: 60_000,
  });
  const salesQ = useQuery({
    queryKey: ["sales-today", d],
    queryFn: () => GET<any>("/sales", { start: d, end: d }),
    refetchInterval: 60_000,
  });
  const insightsQ = useQuery({
    queryKey: ["ai-insights-dash"],
    queryFn: () => GET<any>("/ai/insights"),
    refetchInterval: 90_000,
  });
  const healthQ = useQuery({
    queryKey: ["health-detail-dash"],
    queryFn: () => GET<any>("/health/detail"),
    refetchInterval: 60_000,
  });
  const notifQ = useQuery({
    queryKey: ["notifications-dash"],
    queryFn: () => GET<any>("/notifications", { limit: "8" }),
    refetchInterval: 45_000,
  });

  const wrap = summaryQ.data || {};
  const s = wrap.summary || wrap;
  const cc = ccQ.data || {};
  const products = Array.isArray(productsQ.data)
    ? productsQ.data
    : productsQ.data?.products || [];
  const sales = Array.isArray(salesQ.data) ? salesQ.data : salesQ.data?.sales || [];
  const lowStock = products.filter(
    (p: any) => Number(p.stock || 0) <= Number(p.min_stock ?? 5),
  ).length;

  const revenue = Number(cc.today?.revenue ?? s.total_revenue ?? 0);
  const txns = Number(cc.today?.transactions ?? s.total_transactions ?? sales.length ?? 0);
  const profit = Number(cc.today?.profit ?? 0);
  const monthRev = Number(cc.monthly_revenue ?? 0);
  const expenses = Number(cc.expenses ?? 0);
  const invValue = Number(cc.inventory_value ?? 0);
  const debts = Number(cc.outstanding_debts ?? 0);
  const cashFlow = Number(cc.cash_flow ?? revenue);

  const healthScore = Number(healthQ.data?.score ?? 0);
  const healthOverall = healthQ.data?.overall || "unknown";
  const insights = insightsQ.data || {};
  const activity = Array.isArray(notifQ.data?.notifications)
    ? notifQ.data.notifications
    : [];

  const hourly = useMemo(() => {
    const raw = Array.isArray(wrap.hourly) ? wrap.hourly : [];
    if (raw.length) {
      return raw.map((h: any) => ({
        hour: `${String(h.hour ?? h.label ?? "").padStart(2, "0")}:00`,
        total: Number(h.total || 0),
      }));
    }
    // Derive a simple hourly series from today's sales when API has no hourly
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
    return entries.length ? entries : Object.entries(buckets)
      .slice(8, 20)
      .map(([h, total]) => ({ hour: `${String(h).padStart(2, "0")}:00`, total }));
  }, [wrap.hourly, sales]);

  const byPayment = useMemo(() => {
    const raw = Array.isArray(wrap.by_payment) ? wrap.by_payment : [];
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
  }, [wrap.by_payment, sales]);

  const primaryKpis = [
    {
      key: "sales",
      label: "Today's Sales",
      value: KES(revenue),
      sub: `${txns} receipts`,
      icon: "cart" as const,
      accent: "gold" as const,
    },
    {
      key: "profit",
      label: "Today's Profit",
      value: KES(profit),
      sub: "Est. after cost",
      icon: "dollar" as const,
      accent: "ok" as const,
    },
    {
      key: "month",
      label: "Monthly Revenue",
      value: KES(monthRev),
      sub: "This month",
      icon: "chart" as const,
      accent: "info" as const,
    },
    {
      key: "low",
      label: "Low Stock",
      value: String(lowStock),
      sub: "Products",
      icon: "alert" as const,
      accent: (lowStock ? "warn" : "ok") as "warn" | "ok",
    },
  ];

  const secondaryKpis = [
    {
      key: "exp",
      label: "Expenses",
      value: KES(expenses),
      sub: "Month (if ledger)",
      icon: <Wallet className="h-5 w-5" />,
      accent: "warn" as const,
    },
    {
      key: "inv",
      label: "Inventory Value",
      value: KES(invValue),
      sub: `${products.length} SKUs`,
      icon: <Package className="h-5 w-5" />,
      accent: "info" as const,
    },
    {
      key: "debt",
      label: "Outstanding Debts",
      value: KES(debts),
      sub: "Open invoices",
      icon: <Landmark className="h-5 w-5" />,
      accent: debts > 0 ? ("warn" as const) : ("ok" as const),
    },
    {
      key: "cf",
      label: "Cash Flow",
      value: KES(cashFlow),
      sub: "Today proxy",
      icon: <TrendingUp className="h-5 w-5" />,
      accent: "gold" as const,
    },
  ];

  const ICONS = {
    cart: <ShoppingCart className="h-5 w-5" />,
    dollar: <DollarSign className="h-5 w-5" />,
    chart: <LineChart className="h-5 w-5" />,
    alert: <AlertTriangle className="h-5 w-5" />,
  };

  const loading = summaryQ.isLoading && ccQ.isLoading;

  return (
    <AppShell title="Dashboard">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-6">
        <div className="min-w-0">
          <div className="text-xs text-text2">
            <span className="text-gold font-semibold">{weekday}</span>{" "}
            <span className="mx-1 text-muted-fg">·</span>
            <span>{rest.join(" ")}</span>
          </div>
          <h2 className="text-display text-text mt-1">Welcome back, {name}</h2>
          <div className="text-sm text-text2 mt-0.5">Executive Overview · Live Dashboard</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <div className="flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2 shadow-card">
            <HealthRing score={healthScore} overall={healthOverall} />
            <div className="leading-tight">
              <div className="text-eyebrow">Health</div>
              <div className="text-sm font-semibold text-text capitalize">{healthOverall}</div>
              <Link to="/health" className="text-xs text-gold font-semibold hover:underline">
                Details →
              </Link>
            </div>
          </div>
          <ThemeToggle />
          <Link to="/pos">
            <Button variant="primary" size="touch">
              <Plus className="h-4 w-4" /> New Sale
            </Button>
          </Link>
        </div>
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
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-4">
            {primaryKpis.map((k) => (
              <KpiCard
                key={k.key}
                label={k.label}
                value={k.value}
                sub={k.sub}
                accent={k.accent}
                icon={ICONS[k.icon]}
              />
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
            {secondaryKpis.map((k) => (
              <KpiCard
                key={k.key}
                label={k.label}
                value={k.value}
                sub={k.sub}
                accent={k.accent}
                icon={k.icon}
              />
            ))}
          </div>
        </>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-4 lg:col-span-2">
          <SectionTitle
            action={<span className="text-xs text-text2">Today · hourly</span>}
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
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-4 lg:col-span-1 border-gold/20 bg-gradient-to-b from-gold/[0.06] to-card">
          <SectionTitle
            action={
              <Link to="/ai" className="text-sm text-gold font-semibold inline-flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5" /> AI
              </Link>
            }
          >
            AI Insights
          </SectionTitle>
          <p className="text-sm text-text mb-3 leading-relaxed">
            {insights.summary || "Loading insights…"}
          </p>
          <ul className="space-y-1.5">
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
        </Card>

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
                  {sales.slice(0, 8).map((row: any) => (
                    <tr key={row.id || row.receipt_number}>
                      <td className="px-4 py-2.5 font-mono text-text">
                        {row.receipt_number || row.id}
                      </td>
                      <td className="px-4 py-2.5 tabular-nums font-semibold text-gold">
                        {KES(row.total)}
                      </td>
                      <td className="px-4 py-2.5 text-text2">
                        {String(row.payment_method || "—")}
                      </td>
                      <td className="px-4 py-2.5 text-text2">
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
                      <span className="font-bold text-gold tabular-nums">
                        {KES(row.total)}
                      </span>
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
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
        </Card>

        <Card className="p-4">
          <SectionTitle
            action={
              <Link to="/inventory" className="text-sm text-gold font-semibold">
                Inventory
              </Link>
            }
          >
            Inventory snapshot
          </SectionTitle>
          <div className="flex items-center gap-3 text-sm text-text2 mt-2 mb-4">
            <Package className="h-5 w-5 text-gold" />
            <span>
              <strong className="text-text">{products.length}</strong> products
              {lowStock > 0 ? (
                <>
                  {" "}
                  · <Badge tone="warn">{lowStock} low stock</Badge>
                </>
              ) : null}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/live">
              <Button variant="secondary" size="touch">
                <Activity className="h-4 w-4" /> Live
              </Button>
            </Link>
            <Link to="/approvals">
              <Button variant="secondary" size="touch">
                Approvals
              </Button>
            </Link>
            <Link to="/health">
              <Button variant="secondary" size="touch">
                <HeartPulse className="h-4 w-4" /> Health
              </Button>
            </Link>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
