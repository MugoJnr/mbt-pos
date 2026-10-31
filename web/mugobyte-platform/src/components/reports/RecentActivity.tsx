import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GET } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, type AnalyticsSearch, formatDateTime, formatMoney, rowsOf, value } from "./analytics";

export function RecentActivity({ orgId }: { orgId: string }) {
  const query = useQuery({
    queryKey: ["cloud-activity", orgId],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/activity", { org_id: orgId }),
    enabled: Boolean(orgId),
  });
  const data = query.data || {};
  const sales = rowsOf(data, "sales");
  const repayments = rowsOf(data, "repayments");
  const deliveries = rowsOf(data, "deliveries");
  const batches = rowsOf(data, "sync_batches");

  const item = (row: AnalyticsRow, title: string, search: AnalyticsSearch) => {
    const source = String(value(row, "source_id") || "");
    const device = String(value(row, "device_id") || "");
    if (!source || !device) {
      return (
        <p key={title} className="px-2 py-2 text-sm text-muted-foreground">
          {title} · no record id, so this cannot be opened
        </p>
      );
    }
    return (
      <Link key={`${search.focus}-${source}`} to="/reports" search={{ ...search, device, source }} className="block rounded-lg px-2 py-2 hover:bg-muted/60">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{formatDateTime(value(row, "source_created_at", "started_at", "created_at"))}</p>
      </Link>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent activity</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sales</p>
          {sales.slice(0, 5).map((row) => item(row, `${value(row, "receipt_number") || "Sale"} · ${formatMoney(value(row, "total"))}${String(value(row, "status") || "").toLowerCase().includes("void") ? " · VOID" : ""}`, { tab: "sales", focus: "sale" }))}
          {!sales.length ? <p className="text-sm text-muted-foreground">{query.isLoading ? "Loading…" : "None synced"}</p> : null}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Repayments</p>
          {repayments.slice(0, 5).map((row) => item(row, formatMoney(value(row, "amount")), { tab: "debts", focus: "payment" }))}
          {!repayments.length ? <p className="text-sm text-muted-foreground">{query.isLoading ? "Loading…" : "None synced"}</p> : null}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Deliveries</p>
          {deliveries.slice(0, 5).map((row) => item(row, `${value(row, "supplier_name") || "Supplier"} · ${value(row, "product_name") || ""}`, { tab: "receipts", focus: "delivery" }))}
          {!deliveries.length ? <p className="text-sm text-muted-foreground">{query.isLoading ? "Loading…" : "None synced"}</p> : null}
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sync</p>
          {batches.slice(0, 5).map((row) => (
            <p key={String(value(row, "id"))} className="px-2 py-2 text-sm">
              {String(value(row, "status") || "unknown")} · {formatDateTime(value(row, "started_at"))}
              {value(row, "error") ? <span className="block text-xs text-destructive">{String(value(row, "error"))}</span> : null}
            </p>
          ))}
          {!batches.length ? <p className="text-sm text-muted-foreground">{query.isLoading ? "Loading…" : "No sync batch recorded"}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}
