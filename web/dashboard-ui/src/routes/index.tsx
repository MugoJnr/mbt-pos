import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ShoppingCart,
  DollarSign,
  LineChart,
  AlertTriangle,
  Plus,
  Package,
  BarChart3,
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
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<any>("/products"),
  });
  const salesQ = useQuery({
    queryKey: ["sales-today", d],
    queryFn: () => GET<any>("/sales", { start: d, end: d }),
  });

  const wrap = summaryQ.data || {};
  const s = wrap.summary || wrap;
  const products = Array.isArray(productsQ.data)
    ? productsQ.data
    : productsQ.data?.products || [];
  const sales = Array.isArray(salesQ.data) ? salesQ.data : salesQ.data?.sales || [];
  const lowStock = products.filter(
    (p: any) => Number(p.stock || 0) <= Number(p.min_stock ?? 5),
  ).length;

  const revenue = Number(s.total_revenue ?? 0);
  const txns = Number(s.total_transactions ?? sales.length ?? 0);

  const kpis = [
    {
      key: "sales",
      label: "Today's Sales",
      value: KES(revenue),
      sub: `${txns} receipts`,
      icon: "cart" as const,
      accent: "gold" as const,
    },
    {
      key: "avg",
      label: "Avg Transaction",
      value: KES(Number(s.avg_transaction ?? 0)),
      sub: "Today",
      icon: "dollar" as const,
      accent: "ok" as const,
    },
    {
      key: "txns",
      label: "Transactions",
      value: String(txns),
      sub: "Today",
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

  const ICONS = {
    cart: <ShoppingCart className="h-5 w-5" />,
    dollar: <DollarSign className="h-5 w-5" />,
    chart: <LineChart className="h-5 w-5" />,
    alert: <AlertTriangle className="h-5 w-5" />,
  };

  return (
    <AppShell title="Dashboard">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <div className="text-xs text-text2">
            <span className="text-gold font-semibold">{weekday}</span>{" "}
            <span className="mx-1 text-muted-fg">·</span>
            <span>{rest.join(" ")}</span>
          </div>
          <h2 className="text-[26px] font-extrabold tracking-tight text-text mt-1">
            Welcome back, {name}
          </h2>
          <div className="text-sm text-text2">Daily Overview</div>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link to="/pos">
            <Button variant="primary" size="lg">
              <Plus className="h-4 w-4" /> New Sale
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {kpis.map((k) => (
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
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
          <div className="flex items-center gap-3 text-sm text-text2 mt-2">
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
        </Card>
      </div>
    </AppShell>
  );
}
