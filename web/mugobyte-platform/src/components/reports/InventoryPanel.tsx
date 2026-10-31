import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET, downloadAnalyticsExport } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatMoney, formatNumber, paginationOf, rowsOf, statusVariant, value } from "./analytics";
import { ExportButton, FilterSelect, ReportPagination, SearchBox, Segmented } from "./ReportControls";
import { ReportState, responseError } from "./ReportState";

function categoryOptions(filters: AnalyticsResponse | null | undefined) {
  const categories = filters?.categories;
  if (!Array.isArray(categories)) return [];
  return categories.map((item) => typeof item === "object" && item
    ? { value: String(value(item as AnalyticsRow, "value", "id", "name") || ""), label: String(value(item as AnalyticsRow, "label", "name", "value") || "") }
    : { value: String(item), label: String(item) });
}

export function InventoryPanel({ orgId, start, end, filters, record }: { orgId: string; start: string; end: string; filters?: AnalyticsResponse | null; record?: { device: string; source: string } }) {
  const [stock, setStock] = useState("all");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState<AnalyticsRow | null>(null);
  const detailPath = selected
    ? `/cloud/analytics/products/${encodeURIComponent(String(value(selected, "device_id") || ""))}/${encodeURIComponent(String(value(selected, "source_id") || ""))}`
    : "";
  const detailQ = useQuery({
    queryKey: ["cloud-product", detailPath, orgId],
    queryFn: () => GET<AnalyticsResponse>(detailPath, { org_id: orgId }),
    enabled: Boolean(detailPath && value(selected, "device_id") && value(selected, "source_id")),
  });
  const detail = (detailQ.data?.product || selected || {}) as AnalyticsRow;
  useEffect(() => setPage(1), [stock, search, category, start, end]);
  useEffect(() => {
    if (record?.device && record.source) setSelected({ device_id: record.device, source_id: record.source });
  }, [record?.device, record?.source]);
  const params = { org_id: orgId, start, end, page: String(page), page_size: "25", search, category, stock_status: stock === "all" ? "" : stock };
  const query = useQuery({
    queryKey: ["cloud-analytics-inventory", params],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/inventory", params),
  });
  const rows = rowsOf(query.data, "inventory", "items", "rows", "products");
  const pagination = paginationOf(query.data, rows.length);
  const currency = String(query.data?.currency || "KES");
  const runExport = async () => {
    setExporting(true);
    try {
      await downloadAnalyticsExport({ ...params, page: undefined, page_size: undefined, report: "inventory", format: "csv" });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={stock} onChange={setStock} options={[{ value: "all", label: "All" }, { value: "low", label: "Low stock" }, { value: "out", label: "Out of stock" }]} />
        <div className="basis-full lg:hidden" />
        <SearchBox value={search} onChange={setSearch} placeholder="Product, SKU or barcode…" />
        <FilterSelect value={category} onChange={setCategory} label="Categories" options={categoryOptions(filters)} />
        <ExportButton loading={exporting} onClick={() => void runExport()} />
      </div>
      <Card className="overflow-hidden">
        <ReportState loading={query.isLoading} error={responseError(query.data, query.error)} empty={!rows.length} onRetry={() => void query.refetch()}>
          <Table><TableHeader><TableRow><TableHead>Product</TableHead><TableHead>Category</TableHead><TableHead className="text-right">Stock</TableHead><TableHead className="text-right">Min stock</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Price</TableHead><TableHead className="text-right">Cost</TableHead><TableHead className="text-right">Stock value</TableHead></TableRow></TableHeader>
            <TableBody>{rows.map((row, index) => {
              const quantity = Number(value(row, "stock", "quantity", "stock_quantity") || 0);
              const minimum = Number(value(row, "min_stock", "minimum_stock", "reorder_level") || 0);
              const rowStatus = String(value(row, "stock_status", "status") || (quantity <= 0 ? "Out of stock" : quantity <= minimum ? "Low stock" : "In stock"));
              return <TableRow key={String(value(row, "id", "source_id", "sku") || index)} className="cursor-pointer" onClick={() => setSelected(row)}><TableCell><p className="font-medium">{String(value(row, "product_name", "name") || "Unnamed product")}</p><p className="text-xs text-muted-foreground">{String(value(row, "sku", "barcode") || "")}</p></TableCell><TableCell>{String(value(row, "category_name", "category") || "Uncategorized")}</TableCell><TableCell className="text-right font-semibold">{formatNumber(quantity, 2)}</TableCell><TableCell className="text-right">{formatNumber(minimum, 2)}</TableCell><TableCell><Badge variant={statusVariant(rowStatus)}>{rowStatus}</Badge></TableCell><TableCell className="text-right">{formatMoney(value(row, "price", "selling_price"), currency)}</TableCell><TableCell className="text-right">{value(row, "cost", "cost_price") == null ? "—" : formatMoney(value(row, "cost", "cost_price"), currency)}</TableCell><TableCell className="text-right font-medium">{formatMoney(value(row, "stock_value", "inventory_value") ?? quantity * Number(value(row, "cost", "cost_price") || 0), currency)}</TableCell></TableRow>;
            })}</TableBody>
          </Table>
          <ReportPagination {...pagination} onPage={setPage} />
        </ReportState>
      </Card>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{String(value(detail, "product_name", "name") || "Product")}</DialogTitle>
            <DialogDescription>Latest synced stock. This screen cannot change quantities. Stock value is current product cost times quantity, not remaining FIFO batches.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <p>Category: {String(value(detail, "category") || "—")}</p>
            <p>SKU: {String(value(detail, "sku", "barcode") || "—")}</p>
            <p>Stock: {formatNumber(value(detail, "stock"), 2)}</p>
            <p>Minimum: {formatNumber(value(detail, "min_stock"), 2)}</p>
            <p>Status: {String(value(detail, "stock_status", "status") || "—")}</p>
            <p>Selling price: {formatMoney(value(detail, "price"), currency)}</p>
            <p>Cost: {value(detail, "cost_price") == null ? "—" : formatMoney(value(detail, "cost_price"), currency)}</p>
            <p>Stock value: {value(detail, "stock_value") == null ? "—" : formatMoney(value(detail, "stock_value"), currency)}</p>
          </div>
          <p className="text-xs text-muted-foreground">{detailQ.isLoading ? "Loading recent sales and deliveries…" : "Recent lines are the latest synced records for this product."}</p>
          {Array.isArray(detail.recent_sales) && (detail.recent_sales as AnalyticsRow[]).length ? (
            <div>
              <p className="mb-1 text-sm font-semibold">Recent sales</p>
              {(detail.recent_sales as AnalyticsRow[]).slice(0, 8).map((line, index) => (
                <p key={index} className="text-sm">{String(value(line, "product_name", "name") || "Item")} · qty {String(value(line, "quantity") || 0)} · {formatMoney(value(line, "total"), currency)}</p>
              ))}
            </div>
          ) : null}
          {Array.isArray(detail.recent_movements) && (detail.recent_movements as AnalyticsRow[]).length ? (
            <div>
              <p className="mb-1 text-sm font-semibold">Recent stock lines</p>
              {(detail.recent_movements as AnalyticsRow[]).slice(0, 8).map((line, index) => (
                <p key={index} className="text-sm">{String(value(line, "movement_type") || "Movement")} · {String(value(line, "qty_change") || 0)} · after {String(value(line, "qty_after") || "—")}</p>
              ))}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
