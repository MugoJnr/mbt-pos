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
        {String(query.data?.note || "Suppliers come from the uploaded shop copy. A delivery is not a payment.")}
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
                <TableHead className="text-right">Purchases uploaded</TableHead>
                <TableHead>Payments</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={String(value(row, "name") || index)} className="cursor-pointer" onClick={() => setSelected(row)}>
                  <TableCell className="font-medium">{String(value(row, "name") || "Supplier")}</TableCell>
                  <TableCell>{String(value(row, "phone") || "Not uploaded")}</TableCell>
                  <TableCell className="text-right">{String(value(row, "deliveries") || 0)}</TableCell>
                  <TableCell className="text-right">{row.purchases_uploaded ? String(value(row, "purchase_total") || 0) : "Not uploaded"}</TableCell>
                  <TableCell>{row.payments_uploaded ? String(value(row, "payment_total") || 0) : "Not uploaded"}</TableCell>
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
            <DialogDescription>
              Shop copy of this supplier. A delivery is not the paper invoice, and a missing payment is not a zero balance.
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <p>Contact: {String(value(selected, "contact") || "Not uploaded")}</p>
              <p>Phone: {String(value(selected, "phone") || "Not uploaded")}</p>
              <p>Email: {String(value(selected, "email") || "Not uploaded")}</p>
              <p>Address: {String(value(selected, "address") || "Not uploaded")}</p>
              <p>Status: {String(value(selected, "status") || "Not uploaded")}</p>
              <p>Added: {formatDateTime(value(selected, "created_at"))}</p>
              <p>Updated: {formatDateTime(value(selected, "updated_at"))}</p>
              <p>Deliveries: {String(value(selected, "deliveries") || 0)}</p>
              <p>Purchases: {selected.purchases_uploaded ? String(value(selected, "purchase_total") || 0) : "Not uploaded"}</p>
              <p>Payments: {selected.payments_uploaded ? String(value(selected, "payment_total") || 0) : "Not uploaded"}</p>
              <p>Outstanding: {selected.payments_uploaded && selected.purchases_uploaded ? String(value(selected, "outstanding") ?? "Not uploaded") : "Not uploaded"}</p>
            </div>
          ) : null}
          {selected ? (
            <p className="text-sm text-muted-foreground">
              Statement: this page lists the uploaded deliveries and any uploaded purchase totals. It does not invent a supplier invoice or a payment. Outstanding stays blank until both the purchases and the payments are on the uploaded record.
            </p>
          ) : null}
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
