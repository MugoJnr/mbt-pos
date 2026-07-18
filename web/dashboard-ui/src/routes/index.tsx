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
import { useQuery } from "@tanstack/react-query";
import { AppShell, ThemeToggle } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState, KpiCard, SectionTitle, Table } from "@/components/ui-kit";
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
      <span className="absolute inset-0 grid place-items-center text-sm font-extrabold text-text">
        {score}
      </span>
    </Link>
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

  return (
    <AppShell title="Dashboard">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-6">
        <div className="min-w-0">
          <div className="text-xs text-text2">
            <span className="text-gold font-semibold">{weekday}</span>{" "}
            <span className="mx-1 text-muted-fg">·</span>
            <span>{rest.join(" ")}</span>
          </div>
          <h2 className="text-[22px] sm:text-[26px] font-extrabold tracking-tight text-text mt-1">
            Welcome back, {name}
          </h2>
          <div className="text-sm text-text2">Executive Overview · Command Center</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
            <HealthRing score={healthScore} overall={healthOverall} />
            <div className="leading-tight">
              <div className="text-[10px] tracking-[0.14em] uppercase text-text2 font-semibold">
                Health
              </div>
              <div className="text-sm font-semibold text-text capitalize">{healthOverall}</div>
              <Link to="/health" className="text-xs text-gold font-semibold">
                Details →
              </Link>
            </div>
          </div>
          <ThemeToggle />
          <Link to="/pos">
            <Button variant="primary" size="lg" className="min-h-[44px]">
              <Plus className="h-4 w-4" /> New Sale
            </Button>
          </Link>
        </div>
      </div>

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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-4 lg:col-span-1">
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
                  className="text-xs text-text2 pl-2 border-l-2 border-gold/40 leading-snug"
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
              icon={<BarChart3 className="h-8 w-8 text-muted-fg" />}
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
              <Button variant="secondary" className="min-h-[44px]">
                <Activity className="h-4 w-4" /> Live
              </Button>
            </Link>
            <Link to="/approvals">
              <Button variant="secondary" className="min-h-[44px]">
                Approvals
              </Button>
            </Link>
            <Link to="/health">
              <Button variant="secondary" className="min-h-[44px]">
                <HeartPulse className="h-4 w-4" /> Health
              </Button>
            </Link>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
