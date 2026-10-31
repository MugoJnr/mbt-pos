import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatDateTime, rowsOf, value } from "./analytics";
import { ReportState, responseError } from "./ReportState";

export function SuppliersPanel({ orgId, record }: { orgId: string; record?: { name: string } }) {
  const [selected, setSelected] = useState<AnalyticsRow | null>(null);
  const query = useQuery({
    queryKey: ["cloud-suppliers", orgId],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/suppliers", { org_id: orgId }),
    enabled: Boolean(orgId),
  });
  const rows = rowsOf(query.data, "suppliers", "items");
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    if (!record?.name) return;
    const found = rows.find((row) => String(value(row, "name") || "") === record.name);
    if (found) {
      setSelected(found);
      setMissing(false);
    } else if (!query.isLoading) setMissing(true);
  }, [record?.name, query.isLoading, query.data]);

  return (
    <div className="space-y-3">
      {missing ? <p className="rounded-lg border px-3 py-2 text-sm">That supplier is not in the synced deliveries.</p> : null}
      <p className="text-sm text-muted-foreground">
        Suppliers are grouped from synced deliveries. Phone is shown only when the delivery record contains it. Supplier balances, payments and returns are not in that record, so this page does not show what the shop owes.
      </p>
      <Card className="overflow-hidden">
        <ReportState
          loading={query.isLoading}
          error={responseError(query.data, query.error)}
          empty={!rows.length}
          emptyTitle="No suppliers in the latest sync"
          emptyHint="Deliveries appear here after the till syncs a supplier receipt."
          onRetry={() => void query.refetch()}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Supplier</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead className="text-right">Deliveries</TableHead>
                <TableHead>Products</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={String(value(row, "name") || index)} className="cursor-pointer" onClick={() => setSelected(row)}>
                  <TableCell className="font-medium">{String(value(row, "name") || "Supplier")}</TableCell>
                  <TableCell>{String(value(row, "phone") || "Not on the synced delivery")}</TableCell>
                  <TableCell className="text-right">{String(value(row, "deliveries") || 0)}</TableCell>
                  <TableCell className="max-w-xs truncate">{Array.isArray(row.products) ? (row.products as string[]).join(", ") : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ReportState>
      </Card>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{String(value(selected || {}, "name") || "Supplier")}</DialogTitle>
            <DialogDescription>Recent synced deliveries. Stock cannot be changed from here.</DialogDescription>
          </DialogHeader>
          {selected && Array.isArray(selected.recent) ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Received</TableHead>
                  <TableHead className="text-right">After</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(selected.recent as AnalyticsRow[]).map((row, index) => (
                  <TableRow key={index}>
                    <TableCell>{formatDateTime(value(row, "source_created_at", "created_at"))}</TableCell>
                    <TableCell>{String(value(row, "product_name") || "—")}</TableCell>
                    <TableCell className="text-right">+{String(value(row, "qty_change") ?? 0)}</TableCell>
                    <TableCell className="text-right">{String(value(row, "qty_after") ?? "—")}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
