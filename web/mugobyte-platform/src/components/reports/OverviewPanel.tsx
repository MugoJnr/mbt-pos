import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  Clock3,
  CreditCard,
  Receipt,
  WalletCards,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { GET } from "@/lib/api";
import { AnalyticsChartSection } from "./AnalyticsCharts";
import {
  type AnalyticsResponse,
  formatDateTime,
  formatMoney,
  formatNumber,
  rowsOf,
  value,
} from "./analytics";
import { ReportState, responseError } from "./ReportState";

export function OverviewPanel({ orgId, start, end }: { orgId: string; start: string; end: string }) {
  const query = useQuery({
    queryKey: ["cloud-analytics-overview", orgId, start, end],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/overview", { org_id: orgId, start, end }),
    enabled: Boolean(orgId),
  });
  const data = query.data || {};
  const summary = (data.summary || data.kpis || data.data || data) as Record<string, unknown>;
  const currency = String(data.currency || summary.currency || "KES");
  const gross = value(summary, "gross_sales", "sales_total", "revenue");
  const collected = value(summary, "collected_revenue", "collected", "cash_collected");
  const issued = value(summary, "debt_issued", "credit_sales");
  const debtCollected = value(summary, "debt_collected", "debt_payments");
  const outstanding = value(summary, "debt_outstanding", "outstanding_debt", "balance");
  const transactions = value(summary, "transactions", "sales_count", "receipts");
  const trend = rowsOf(data, "trend", "sales_trend", "by_day");
  const methods = rowsOf(data, "payment_methods", "payment_mix");
  const lastSync = value(summary, "last_sync_at", "last_sync") || data.last_sync_at;
  const sync = (summary.sync || {}) as Record<string, unknown>;
  const showProfit = Object.prototype.hasOwnProperty.call(summary, "gross_profit");
  const previous = (data.previous || {}) as { summary?: Record<string, unknown>; start?: string; end?: string };
  const previousGross = Number(value(previous.summary || {}, "gross_sales", "revenue") || 0);
  const hasActivity =
    Number(gross || 0) > 0 ||
    Number(collected || 0) > 0 ||
    Number(issued || 0) > 0 ||
    Number(debtCollected || 0) > 0 ||
    Number(outstanding || 0) > 0 ||
    Number(transactions || 0) > 0 ||
    trend.length > 0 ||
    methods.length > 0 ||
    Boolean(lastSync);
  const emptyHint = lastSync
    ? "No sales in this date range (default is today). Use Last 7 / 30 Days if you need older activity — cloud sync last ran as shown below."
    : "Sign in on the shop PC, open Cloud Backup, and keep the device approved so sales sync to the portal.";
  const cards: Array<[string, string, typeof Receipt, string]> = [
    ["Gross sales", formatMoney(gross, currency), Receipt, "primary"],
    ["Collected revenue", formatMoney(collected, currency), Banknote, "success"],
    ["Debt issued", formatMoney(issued, currency), CreditCard, "info"],
    ["Debt collected", formatMoney(debtCollected, currency), ArrowDownRight, "success"],
    ["Outstanding debt", formatMoney(outstanding, currency), WalletCards, "warning"],
    ["Transactions", formatNumber(transactions), ArrowUpRight, "primary"],
  ];
  if (showProfit) {
    cards.push(
      ["Gross profit", formatMoney(value(summary, "gross_profit"), currency), Banknote, "success"],
      ["Profit on credit and part-payment", formatMoney(value(summary, "gross_profit_credit_and_part"), currency), CreditCard, "info"],
      ["Profit on fully paid sales", formatMoney(value(summary, "gross_profit_fully_paid"), currency), Banknote, "primary"],
      ["Profit still on outstanding debt", formatMoney(value(summary, "gross_profit_outstanding"), currency), WalletCards, "warning"],
    );
  }

  return (
    <ReportState
      loading={query.isLoading}
      error={responseError(query.data, query.error)}
      empty={!query.isLoading && !query.error && !hasActivity}
      emptyTitle="No analytics activity for this range"
      emptyHint={emptyHint}
      onRetry={() => void query.refetch()}
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <p>
            {String(sync.label || (lastSync ? "Last sync succeeded." : "No successful sync has been reported"))}
            {previous.start ? ` Compared with ${previous.start} to ${previous.end}: gross sales were ${formatMoney(previousGross, currency)}.` : ""}
          </p>
          <span className="inline-flex items-center gap-1.5">
            <Clock3 className="h-3.5 w-3.5" />
            Cloud last sync: {lastSync ? formatDateTime(lastSync) : "Not reported"}
          </span>
        </div>
        {sync.stale ? (
          <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground">
            These figures may be behind the till. A failed or missing sync is not treated as a new update.
          </p>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map(([label, amount, Icon, accent]) => (
            <Card key={label} className="border-border/70">
              <CardContent className="flex items-start justify-between p-5">
                <div>
                  <p className="text-sm text-muted-foreground">{label}</p>
                  <p className="mt-2 text-xl font-semibold tracking-tight">{amount}</p>
                </div>
                <span
                  className={
                    accent === "success"
                      ? "rounded-lg bg-success/15 p-2 text-success"
                      : accent === "warning"
                        ? "rounded-lg bg-warning/15 p-2 text-warning"
                        : accent === "info"
                          ? "rounded-lg bg-info/15 p-2 text-info"
                          : "rounded-lg bg-primary/10 p-2 text-primary"
                  }
                >
                  <Icon className="h-4 w-4" />
                </span>
              </CardContent>
            </Card>
          ))}
        </div>
        <AnalyticsChartSection trendRows={trend} mixRows={methods} currency={currency} />
      </div>
    </ReportState>
  );
}
