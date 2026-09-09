import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CloudOff,
  CloudUpload,
  Eye,
  MonitorSmartphone,
  Radio,
  RefreshCw,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AnalyticsChartSection } from "./AnalyticsCharts";
import {
  type AnalyticsResponse,
  type ShopPresence,
  formatCompactMoney,
  formatDateTime,
  formatMoney,
  formatNumber,
  formatRelativeSync,
  profitKpiFromSummary,
  rowsOf,
  value,
} from "./analytics";
import { ReportState, responseError } from "./ReportState";

function PresenceStrip({
  presence,
  onRefresh,
  refreshing,
}: {
  presence: ShopPresence;
  onRefresh: () => void;
  refreshing?: boolean;
}) {
  const freshness = String(presence.sync_freshness || "never");
  const pcOnline = Boolean(presence.pc_online);
  const syncTone =
    freshness === "fresh"
      ? "border-success/30 bg-success/10 text-success"
      : freshness === "aging"
        ? "border-warning/30 bg-warning/10 text-warning"
        : "border-destructive/30 bg-destructive/10 text-destructive";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
          pcOnline
            ? "border-success/30 bg-success/10 text-success"
            : "border-border bg-muted/60 text-muted-foreground",
        )}
      >
        {pcOnline ? <Radio className="h-3.5 w-3.5" /> : <MonitorSmartphone className="h-3.5 w-3.5" />}
        Shop PC {pcOnline ? "online" : "offline"}
      </span>
      <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", syncTone)}>
        {freshness === "stale" || freshness === "never" ? (
          <CloudOff className="h-3.5 w-3.5" />
        ) : (
          <CloudUpload className="h-3.5 w-3.5" />
        )}
        {presence.is_live_data
          ? `Synced ${formatRelativeSync(presence.last_sync_at)}`
          : `${presence.data_label || "Sync"} · ${formatRelativeSync(presence.last_sync_at)}`}
      </span>
      <Button
        size="sm"
        variant="ghost"
        className="h-8 gap-1.5 rounded-full px-2.5"
        onClick={onRefresh}
        disabled={refreshing}
      >
        <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
        Refresh
      </Button>
    </div>
  );
}

function KpiButton({
  label,
  amount,
  hint,
  onClick,
  accent,
}: {
  label: string;
  amount: string;
  hint?: string;
  onClick?: () => void;
  accent?: "primary" | "success" | "warning" | "info";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group rounded-2xl border border-border/70 bg-card/80 p-4 text-left transition",
        "hover:border-primary/35 hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-2 font-display text-2xl font-semibold tracking-tight tabular-nums sm:text-[1.65rem]",
          accent === "success" && "text-success",
          accent === "warning" && "text-warning",
          accent === "info" && "text-info",
        )}
      >
        {amount}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-muted-foreground opacity-0 transition group-hover:opacity-100">
        Open <ArrowRight className="h-3 w-3" />
      </span>
    </button>
  );
}

export function OverviewPanel({
  orgId,
  start,
  end,
  shopName,
  onNavigateTab,
}: {
  orgId: string;
  start: string;
  end: string;
  shopName?: string;
  onNavigateTab?: (tab: string) => void;
}) {
  const query = useQuery({
    queryKey: ["cloud-analytics-overview", orgId, start, end],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/overview", { org_id: orgId, start, end }),
    enabled: Boolean(orgId),
    refetchInterval: 90_000,
  });
  const data = query.data || {};
  const summary = (data.summary || data.kpis || data.data || data) as Record<string, unknown>;
  const currency = String(data.currency || summary.currency || "KES");
  const presence = (data.presence || data.shop_status || {}) as ShopPresence;
  const lastSync =
    presence.last_sync_at ||
    value(summary, "last_sync_at", "last_sync") ||
    data.last_sync_at;

  const resolvedPresence: ShopPresence = {
    ...presence,
    last_sync_at: (lastSync as string) || presence.last_sync_at || null,
    sync_freshness: presence.sync_freshness || (lastSync ? "aging" : "never"),
    data_label: presence.data_label,
    is_live_data: Boolean(presence.is_live_data),
    pc_online: Boolean(presence.pc_online),
  };

  const gross = value(summary, "gross_sales", "sales_total", "revenue");
  const profit = value(summary, "gross_profit", "profit");
  const outstanding = value(summary, "debt_outstanding", "outstanding_debt", "balance");
  const inventoryValue = value(summary, "inventory_value");
  const transactions = value(summary, "transactions", "sales_count", "receipts");
  const margin = value(summary, "gross_margin_pct", "margin_pct");
  const profitKpi = profitKpiFromSummary(summary, profit, margin, currency);
  const costIncomplete = false; // never block the KPI; soft note goes in Needs Attention
  const costMessage = "";

  const trend = rowsOf(data, "trend", "sales_trend", "by_day");
  const methods = rowsOf(data, "payment_methods", "payment_mix");
  const attention = rowsOf(data, "attention");
  const lowStock = rowsOf(data, "low_stock");
  const recentSales = rowsOf(data, "recent_sales");
  const topDebtors = rowsOf(data, "top_debtors");
  const topProducts = rowsOf(data, "top_products");

  const staleBanner =
    resolvedPresence.sync_freshness === "stale" || resolvedPresence.sync_freshness === "never";

  const hasActivity =
    Number(gross || 0) > 0 ||
    (!costIncomplete && Number(profit ?? 0) !== 0) ||
    Number(outstanding || 0) > 0 ||
    Number(inventoryValue || 0) > 0 ||
    Number(transactions || 0) > 0 ||
    trend.length > 0 ||
    methods.length > 0 ||
    Boolean(lastSync);

  const emptyHint = lastSync
    ? "No sales in this date range. Try Last 7 / 30 Days — cloud sync last ran as shown above."
    : "Sign in on the shop PC, open Cloud Backup, and keep the device approved so sales sync here.";

  const go = (tab: string) => onNavigateTab?.(tab);

  return (
    <ReportState
      loading={query.isLoading}
      error={responseError(query.data, query.error)}
      empty={!query.isLoading && !query.error && !hasActivity}
      emptyTitle="No analytics activity for this range"
      emptyHint={emptyHint}
      onRetry={() => void query.refetch()}
    >
      <div className="space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              MugoByte · Shop command center
            </p>
            <h2 className="mt-1 font-display text-2xl font-semibold tracking-tight sm:text-3xl">
              {shopName || "Your shop"}
            </h2>
            <p className="mt-1 max-w-xl text-sm text-muted-foreground">
              Sales, profit, debt and inventory from synced cloud data — not a live till feed.
            </p>
          </div>
          <PresenceStrip
            presence={resolvedPresence}
            onRefresh={() => void query.refetch()}
            refreshing={query.isFetching}
          />
        </div>

        {staleBanner ? (
          <div className="flex gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-medium text-foreground">
                {resolvedPresence.sync_freshness === "never"
                  ? "This shop has never synced business data"
                  : "Business data is stale — not LIVE"}
              </p>
              <p className="mt-0.5 text-muted-foreground">
                {resolvedPresence.pc_online
                  ? "Shop PC is online, but the last successful sync is old. Historical figures below remain usable."
                  : "Shop PC appears offline. You can still review the last synced figures and refresh after sync resumes."}
                {lastSync ? ` Last sync ${formatDateTime(lastSync)}.` : ""}
              </p>
            </div>
          </div>
        ) : null}

        {costIncomplete ? (
          <div className="flex gap-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-medium text-foreground">
                {String(summary.cost_data_status || "") === "partial"
                  ? "Partial profit — some lines missing cost"
                  : "Cost data incomplete — profit unavailable"}
              </p>
              <p className="mt-0.5 text-muted-foreground">
                {costMessage ||
                  "Some sale lines are missing unit cost (and no usable product cost). Sales KPIs still show; margin is hidden so it is not invented."}
              </p>
            </div>
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiButton
            label={start === end ? "Sales today" : "Sales"}
            amount={formatCompactMoney(gross, currency)}
            hint={`${formatNumber(transactions)} transactions`}
            onClick={() => go("sales")}
          />
          <KpiButton
            label={start === end ? "Gross profit today" : "Gross profit"}
            amount={profitKpi.amount}
            hint={profitKpi.hint}
            accent="success"
            onClick={() => go("sales")}
          />
          <KpiButton
            label="Outstanding debt"
            amount={formatCompactMoney(outstanding, currency)}
            hint={`${formatNumber(value(summary, "outstanding_count"))} open invoices`}
            accent="warning"
            onClick={() => go("debts")}
          />
          <KpiButton
            label="Inventory value"
            amount={
              inventoryValue == null ? "—" : formatCompactMoney(inventoryValue, currency)
            }
            hint={(() => {
              const lowOnly = Number(value(summary, "low_only_count") ?? 0) || 0;
              const outCount = Number(value(summary, "out_of_stock_count") ?? 0) || 0;
              const combined = Number(value(summary, "low_stock_count") ?? lowOnly + outCount) || 0;
              if (combined <= 0) return "All stocked";
              if (outCount > 0 && lowOnly > 0) {
                return `${formatNumber(combined)} low/out of stock`;
              }
              if (outCount > 0) return `${formatNumber(outCount)} out of stock`;
              return `${formatNumber(lowOnly || combined)} need attention`;
            })()}
            accent="info"
            onClick={() => go("inventory")}
          />
        </div>

        <AnalyticsChartSection
          trendRows={trend}
          mixRows={methods}
          currency={currency}
          costIncomplete={costIncomplete}
        />

        <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
          <Card className="border-border/70">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <AlertTriangle className="h-4 w-4 text-warning" />
                Needs attention
              </CardTitle>
              <CardDescription>Rule-based signals only — no AI guesses.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {attention.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border/70 px-3 py-6 text-center text-sm text-muted-foreground">
                  Nothing urgent for this shop right now.
                </p>
              ) : (
                attention.map((item) => {
                  const severity = String(value(item, "severity") || "info");
                  return (
                    <button
                      key={String(value(item, "id", "title"))}
                      type="button"
                      className="flex w-full items-start gap-3 rounded-xl border border-border/60 bg-muted/20 px-3 py-2.5 text-left transition hover:bg-muted/40"
                      onClick={() => go(String(value(item, "action") || "overview"))}
                    >
                      <Badge
                        variant={
                          severity === "critical"
                            ? "destructive"
                            : severity === "warning"
                              ? "secondary"
                              : "outline"
                        }
                        className="mt-0.5 shrink-0 capitalize"
                      >
                        {severity}
                      </Badge>
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">
                          {String(value(item, "title") || "")}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {String(value(item, "detail") || "")}
                        </span>
                      </span>
                    </button>
                  );
                })
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Boxes className="h-4 w-4 text-primary" />
                  Inventory watch
                </CardTitle>
                <CardDescription>Low and out-of-stock products from the last sync.</CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={() => go("inventory")}>
                Open inventory
              </Button>
            </CardHeader>
            <CardContent>
              {lowStock.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border/70 px-3 py-6 text-center text-sm text-muted-foreground">
                  Stock levels look healthy.
                </p>
              ) : (
                <div className="overflow-hidden rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Product</TableHead>
                        <TableHead className="text-right">Stock</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {lowStock.slice(0, 8).map((row, index) => {
                        const qty = Number(value(row, "stock") || 0);
                        const status = qty <= 0 ? "Out" : "Low";
                        return (
                          <TableRow key={String(value(row, "source_id", "sku") || index)}>
                            <TableCell>
                              <p className="font-medium">{String(value(row, "name") || "Product")}</p>
                              <p className="text-xs text-muted-foreground">
                                {String(value(row, "sku", "category") || "")}
                              </p>
                            </TableCell>
                            <TableCell className="text-right font-semibold tabular-nums">
                              {formatNumber(qty, 2)}
                            </TableCell>
                            <TableCell>
                              <Badge variant={qty <= 0 ? "destructive" : "secondary"}>{status}</Badge>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="border-border/70">
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <WalletCards className="h-4 w-4 text-warning" />
                  Debt snapshot
                </CardTitle>
                <CardDescription>Top debtors by outstanding balance.</CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={() => go("debts")}>
                Open ledger
              </Button>
            </CardHeader>
            <CardContent>
              {topDebtors.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border/70 px-3 py-6 text-center text-sm text-muted-foreground">
                  No open debt invoices.
                </p>
              ) : (
                <div className="space-y-2">
                  {topDebtors.slice(0, 6).map((row, index) => (
                    <div
                      key={String(value(row, "name") || index)}
                      className="flex items-center justify-between gap-3 rounded-xl border border-border/60 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">{String(value(row, "name") || "Unknown")}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatNumber(value(row, "invoices"))} invoice
                          {Number(value(row, "invoices") || 0) === 1 ? "" : "s"}
                          {value(row, "phone") ? ` · ${String(value(row, "phone"))}` : ""}
                        </p>
                      </div>
                      <p className="shrink-0 font-semibold tabular-nums">
                        {formatMoney(value(row, "balance"), currency)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <TrendingUp className="h-4 w-4 text-primary" />
                  Top products
                </CardTitle>
                <CardDescription>By revenue in the selected period.</CardDescription>
              </div>
              <Button size="sm" variant="outline" onClick={() => go("inventory")}>
                Inventory
              </Button>
            </CardHeader>
            <CardContent>
              {topProducts.length === 0 ? (
                <p className="rounded-xl border border-dashed border-border/70 px-3 py-6 text-center text-sm text-muted-foreground">
                  No product sales in this range.
                </p>
              ) : (
                <div className="space-y-2">
                  {topProducts.slice(0, 6).map((row, index) => (
                    <div
                      key={String(value(row, "name") || index)}
                      className="flex items-center justify-between gap-3 rounded-xl border border-border/60 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">{String(value(row, "name") || "Item")}</p>
                        <p className="text-xs text-muted-foreground">
                          Qty {formatNumber(value(row, "qty"), 2)}
                          {row.cost_data_incomplete
                            ? " · cost incomplete"
                            : value(row, "profit") != null
                              ? ` · profit ${formatMoney(value(row, "profit"), currency)}`
                              : ""}
                        </p>
                      </div>
                      <p className="shrink-0 font-semibold tabular-nums">
                        {formatMoney(value(row, "revenue"), currency)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="border-border/70">
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
            <div>
              <CardTitle className="text-base">Recent sales</CardTitle>
              <CardDescription>Latest synced receipts in this range.</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => go("sales")}>
              All sales
            </Button>
          </CardHeader>
          <CardContent>
            {recentSales.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border/70 px-3 py-6 text-center text-sm text-muted-foreground">
                No recent sales for this period.
              </p>
            ) : (
              <div className="overflow-hidden rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Receipt</TableHead>
                      <TableHead>Customer</TableHead>
                      <TableHead>Payment</TableHead>
                      <TableHead className="text-right">Total</TableHead>
                      <TableHead className="w-16" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {recentSales.slice(0, 10).map((row, index) => (
                      <TableRow key={String(value(row, "source_id", "receipt_number") || index)}>
                        <TableCell className="whitespace-nowrap text-sm">
                          {formatDateTime(value(row, "source_created_at", "created_at"))}
                        </TableCell>
                        <TableCell className="font-medium">
                          {String(value(row, "receipt_number", "receipt") || "—")}
                        </TableCell>
                        <TableCell>{String(value(row, "customer_name") || "Walk-in")}</TableCell>
                        <TableCell>{String(value(row, "payment_method") || "—")}</TableCell>
                        <TableCell className="text-right font-semibold tabular-nums">
                          {formatMoney(value(row, "total"), currency)}
                        </TableCell>
                        <TableCell>
                          <Button size="sm" variant="ghost" onClick={() => go("sales")}>
                            <Eye className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ReportState>
  );
}
