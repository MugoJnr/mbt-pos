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
  const hasActivity =
    Number(gross || 0) > 0 ||
    Number(collected || 0) > 0 ||
    Number(transactions || 0) > 0 ||
    trend.length > 0 ||
    methods.length > 0;
  const cards = [
    ["Gross sales", formatMoney(gross, currency), Receipt, "primary"],
    ["Collected revenue", formatMoney(collected, currency), Banknote, "success"],
    ["Debt issued", formatMoney(issued, currency), CreditCard, "info"],
    ["Debt collected", formatMoney(debtCollected, currency), ArrowDownRight, "success"],
    ["Outstanding debt", formatMoney(outstanding, currency), WalletCards, "warning"],
    ["Transactions", formatNumber(transactions), ArrowUpRight, "primary"],
  ] as const;

  return (
    <ReportState
      loading={query.isLoading}
      error={responseError(query.data, query.error)}
      empty={!query.isLoading && !query.error && !hasActivity}
      onRetry={() => void query.refetch()}
    >
      <div className="space-y-5">
        <div className="flex items-center justify-end gap-1.5 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          Cloud last sync: {lastSync ? formatDateTime(lastSync) : "Not reported"}
        </div>
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
