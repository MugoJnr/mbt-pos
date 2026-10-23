import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatDateTime, formatMoney, rowsOf, value } from "./analytics";
import { ReportState, responseError } from "./ReportState";

export function ReceiptsPanel({ orgId }: { orgId: string }) {
  const [selected, setSelected] = useState<AnalyticsRow | null>(null);
  const query = useQuery({
    queryKey: ["cloud-analytics-stock-receipts", orgId],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/stock-receipts", { org_id: orgId }),
    enabled: Boolean(orgId),
  });
  const rows = rowsOf(query.data, "receipts", "items", "rows");

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <ReportState
          loading={query.isLoading}
          error={responseError(query.data, query.error)}
          empty={!rows.length}
          emptyTitle="No supplier receipts in this sync"
          emptyHint="Receive stock on the till. The receipt appears here after the shop syncs."
          onRetry={() => void query.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Supplier</TableHead>
                <TableHead>Product</TableHead>
                <TableHead className="text-right">Received</TableHead>
                <TableHead className="text-right">After</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow
                  key={String(value(row, "id", "source_id") || index)}
                  className="cursor-pointer"
                  onClick={() => setSelected(row)}
                >
                  <TableCell className="whitespace-nowrap">
                    {formatDateTime(value(row, "created_at", "source_created_at"))}
                  </TableCell>
                  <TableCell>
                    <p className="font-medium">{String(value(row, "supplier_name") || "No supplier")}</p>
                    <p className="text-xs text-muted-foreground">{String(value(row, "supplier_phone") || "")}</p>
                  </TableCell>
                  <TableCell>{String(value(row, "product_name", "name") || "—")}</TableCell>
                  <TableCell className="text-right font-semibold">
                    +{String(value(row, "qty_change") ?? 0)}
                  </TableCell>
                  <TableCell className="text-right">{String(value(row, "qty_after") ?? "—")}</TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost" onClick={() => setSelected(row)}>
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ReportState>
      </Card>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{String(value(selected || {}, "product_name", "name") || "Product")}</DialogTitle>
            <DialogDescription>
              {formatDateTime(value(selected || {}, "created_at", "source_created_at"))}
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <div className="space-y-4 text-sm">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Product</p>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  {[
                    ["Name", value(selected, "product_name", "name")],
                    ["Category", value(selected, "category")],
                    ["SKU", value(selected, "sku")],
                    ["Barcode", value(selected, "barcode")],
                    ["Selling price", formatMoney(value(selected, "price"), "KES")],
                    ["Cost", formatMoney(value(selected, "cost_price"), "KES")],
                    ["Unit", value(selected, "unit") || "pcs"],
                    ["On hand now", value(selected, "current_stock")],
                    ["Low-stock alert", value(selected, "min_stock")],
                  ].map(([label, item]) => (
                    <div key={String(label)}>
                      <p className="text-xs text-muted-foreground">{String(label)}</p>
                      <p className="mt-1 font-medium">{String(item || "—")}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">This delivery</p>
                <div className="mt-2 grid gap-3 sm:grid-cols-2">
                  {[
                    ["Supplier", value(selected, "supplier_name")],
                    ["Phone", value(selected, "supplier_phone")],
                    ["Supplier note", value(selected, "supplier_notes")],
                    ["Quantity received", `+${value(selected, "qty_change") ?? 0} ${value(selected, "unit") || "pcs"}`],
                    ["Stock before", value(selected, "qty_before")],
                    ["Stock after", value(selected, "qty_after")],
                    ["Received by", value(selected, "username", "cashier_name")],
                  ].map(([label, item]) => (
                    <div key={String(label)}>
                      <p className="text-xs text-muted-foreground">{String(label)}</p>
                      <p className="mt-1 font-medium">{String(item || "—")}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Delivery note</p>
                <p className="mt-1">{String(value(selected, "reason", "notes") || "—")}</p>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
