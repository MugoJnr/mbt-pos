import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET, downloadAnalyticsExport } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatDateTime, formatMoney, formatNumber, paginationOf, rowsOf, statusVariant, value } from "./analytics";
import { ExportButton, FilterSelect, ReportPagination, SearchBox } from "./ReportControls";
import { ReportState, responseError } from "./ReportState";

const optionRows = (data: AnalyticsResponse | null | undefined, key: string) => {
  const values = data?.[key];
  if (!Array.isArray(values)) return [];
  return values.map((item) => typeof item === "object" && item ? {
    value: String(value(item as AnalyticsRow, "value", "id", "name") || ""),
    label: String(value(item as AnalyticsRow, "label", "name", "value") || ""),
  } : { value: String(item), label: String(item) });
};

export function SalesPanel({ orgId, start, end, filters }: { orgId: string; start: string; end: string; filters?: AnalyticsResponse | null }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [payment, setPayment] = useState("");
  const [cashier, setCashier] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AnalyticsRow | null>(null);
  const [exporting, setExporting] = useState(false);
  useEffect(() => setPage(1), [search, status, payment, cashier, start, end]);
  const params = { org_id: orgId, start, end, page: String(page), page_size: "25", search, status, payment_method: payment, cashier };
  const query = useQuery({
    queryKey: ["cloud-analytics-sales", params],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/sales", params),
  });
  const rows = rowsOf(query.data, "sales", "items", "rows");
  const pagination = paginationOf(query.data, rows.length);
  const currency = String(query.data?.currency || "KES");
  const detailPath = selected
    ? `/cloud/analytics/sales/${encodeURIComponent(String(value(selected, "device_id") || ""))}/${encodeURIComponent(String(value(selected, "source_id", "id", "sale_id") || ""))}`
    : "";
  const detailQ = useQuery({
    queryKey: ["cloud-analytics-sale-detail", detailPath, orgId],
    queryFn: () => GET<AnalyticsResponse>(detailPath, { org_id: orgId }),
    enabled: Boolean(selected && value(selected, "device_id") && value(selected, "source_id", "id", "sale_id")),
  });
  const detail = ((detailQ.data?.sale || detailQ.data?.data || selected || {}) as AnalyticsRow);
  const lineItems = rowsOf(detailQ.data, "line_items", "items", "lines").length
    ? rowsOf(detailQ.data, "line_items", "items", "lines")
    : (Array.isArray(detail.line_items) ? detail.line_items as AnalyticsRow[] : []);
  const runExport = async () => {
    setExporting(true);
    try {
      await downloadAnalyticsExport({ ...params, page: undefined, page_size: undefined, report: "sales", format: "csv" });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <SearchBox value={search} onChange={setSearch} placeholder="Receipt, customer or cashier…" />
        <FilterSelect value={status} onChange={setStatus} label="Statuses" options={optionRows(filters, "statuses")} />
        <FilterSelect value={payment} onChange={setPayment} label="Payments" options={optionRows(filters, "payment_methods")} />
        <FilterSelect value={cashier} onChange={setCashier} label="Cashiers" options={optionRows(filters, "cashiers")} />
        <ExportButton loading={exporting} onClick={() => void runExport()} />
      </div>
      <Card className="overflow-hidden">
        <ReportState loading={query.isLoading} error={responseError(query.data, query.error)} empty={!rows.length} onRetry={() => void query.refetch()}>
          <Table>
            <TableHeader><TableRow><TableHead>Date / time</TableHead><TableHead>Receipt</TableHead><TableHead>Cashier</TableHead><TableHead>Customer</TableHead><TableHead>Payment</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Total</TableHead><TableHead className="w-20" /></TableRow></TableHeader>
            <TableBody>{rows.map((row, index) => {
              const rowStatus = value(row, "status", "sale_status") || "Completed";
              return <TableRow key={String(value(row, "id", "source_id", "receipt_number") || index)}>
                <TableCell className="whitespace-nowrap">{formatDateTime(value(row, "sold_at", "source_created_at", "created_at", "date", "timestamp"))}</TableCell>
                <TableCell className="font-medium">{String(value(row, "receipt_number", "receipt", "invoice_number") || "—")}</TableCell>
                <TableCell>{String(value(row, "cashier_name", "cashier") || "—")}</TableCell>
                <TableCell>{String(value(row, "customer_name", "customer") || "Walk-in")}</TableCell>
                <TableCell>{String(value(row, "payment_method", "payment") || "—")}</TableCell>
                <TableCell><Badge variant={statusVariant(rowStatus)}>{String(rowStatus)}</Badge></TableCell>
                <TableCell className="text-right font-semibold">{formatMoney(value(row, "total", "grand_total", "amount"), currency)}</TableCell>
                <TableCell><Button size="sm" variant="ghost" onClick={() => setSelected(row)}><Eye className="mr-1 h-4 w-4" />View</Button></TableCell>
              </TableRow>;
            })}</TableBody>
          </Table>
          <ReportPagination {...pagination} onPage={setPage} />
        </ReportState>
      </Card>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Sale {String(value(detail, "receipt_number", "receipt", "invoice_number") || "")}</DialogTitle>
            <DialogDescription>{formatDateTime(value(detail, "sold_at", "created_at", "date"))} · {String(value(detail, "status") || "Completed")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 rounded-lg bg-muted/40 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {[["Cashier", value(detail, "cashier_name", "cashier")], ["Customer", value(detail, "customer_name", "customer") || "Walk-in"], ["Phone", value(detail, "customer_phone", "phone")], ["Payment", value(detail, "payment_method", "payment")], ["Subtotal", formatMoney(value(detail, "subtotal"), currency)], ["Discount", formatMoney(value(detail, "discount", "discount_total"), currency)], ["Tax", formatMoney(value(detail, "tax", "tax_total"), currency)], ["Total", formatMoney(value(detail, "total", "grand_total", "amount"), currency)]].map(([label, item]) => <div key={String(label)}><p className="text-xs text-muted-foreground">{String(label)}</p><p className="mt-1 font-medium">{String(item || "—")}</p></div>)}
          </div>
          <div className="overflow-hidden rounded-lg border">
            <Table><TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Price</TableHead><TableHead className="text-right">Discount</TableHead><TableHead className="text-right">Total</TableHead></TableRow></TableHeader>
              <TableBody>{lineItems.length ? lineItems.map((line, index) => <TableRow key={String(value(line, "id", "product_id") || index)}><TableCell><p className="font-medium">{String(value(line, "product_name", "name", "description") || "Item")}</p><p className="text-xs text-muted-foreground">{String(value(line, "sku", "barcode") || "")}</p></TableCell><TableCell className="text-right">{formatNumber(value(line, "quantity", "qty"), 2)}</TableCell><TableCell className="text-right">{formatMoney(value(line, "unit_price", "price"), currency)}</TableCell><TableCell className="text-right">{formatMoney(value(line, "discount", "discount_amount"), currency)}</TableCell><TableCell className="text-right font-medium">{formatMoney(value(line, "total", "line_total", "amount"), currency)}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className="py-8 text-center text-muted-foreground">{detailQ.isLoading ? "Loading line items…" : "No line items supplied."}</TableCell></TableRow>}</TableBody>
            </Table>
          </div>
          {value(detail, "notes", "note") ? <p className="text-sm"><span className="text-muted-foreground">Notes: </span>{String(value(detail, "notes", "note"))}</p> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
