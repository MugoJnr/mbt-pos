import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET, downloadAnalyticsExport } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatDateTime, formatMoney, paginationOf, rowsOf, statusVariant, value } from "./analytics";
import { ExportButton, FilterSelect, ReportPagination, SearchBox, Segmented } from "./ReportControls";
import { ReportState, responseError } from "./ReportState";

const debtStatuses = [
  { value: "open", label: "Open" },
  { value: "partial", label: "Partially paid" },
  { value: "paid", label: "Paid" },
  { value: "overdue", label: "Overdue" },
];

export function DebtsPanel({ orgId, start, end }: { orgId: string; start: string; end: string }) {
  const [view, setView] = useState("invoices");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  useEffect(() => setPage(1), [view, search, status, start, end]);
  const params = { org_id: orgId, start, end, page: String(page), page_size: "25", search, status };
  const endpoint = view === "payments" ? "/cloud/analytics/debt-payments" : "/cloud/analytics/debts";
  const query = useQuery({
    queryKey: ["cloud-analytics-debts", endpoint, params],
    queryFn: () => GET<AnalyticsResponse>(endpoint, params),
  });
  const rows = rowsOf(query.data, view === "payments" ? "payments" : "debts", "items", "rows");
  const pagination = paginationOf(query.data, rows.length);
  const currency = String(query.data?.currency || "KES");
  const runExport = async () => {
    setExporting(true);
    try {
      await downloadAnalyticsExport({ ...params, page: undefined, page_size: undefined, report: view === "payments" ? "debt-payments" : "debts", format: "csv" });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={view} onChange={setView} options={[{ value: "invoices", label: "Debt invoices" }, { value: "payments", label: "Payment history" }]} />
        <div className="basis-full lg:hidden" />
        <SearchBox value={search} onChange={setSearch} placeholder="Party, phone or receipt…" />
        {view === "invoices" ? <FilterSelect value={status} onChange={setStatus} label="Statuses" options={debtStatuses} /> : null}
        <ExportButton loading={exporting} onClick={() => void runExport()} />
      </div>
      <Card className="overflow-hidden">
        <ReportState loading={query.isLoading} error={responseError(query.data, query.error)} empty={!rows.length} onRetry={() => void query.refetch()}>
          {view === "invoices" ? (
            <Table><TableHeader><TableRow><TableHead>Party</TableHead><TableHead>Receipt / invoice</TableHead><TableHead className="text-right">Original</TableHead><TableHead className="text-right">Paid</TableHead><TableHead className="text-right">Balance</TableHead><TableHead>Due / created</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((row, index) => {
                const rowStatus = value(row, "status", "debt_status") || (Number(value(row, "balance") || 0) <= 0 ? "Paid" : "Open");
                return <TableRow key={String(value(row, "id", "source_id", "invoice_number") || index)}><TableCell><p className="font-medium">{String(value(row, "party_name", "customer_name", "name") || "Unknown")}</p><p className="text-xs text-muted-foreground">{String(value(row, "party_phone", "customer_phone", "phone") || "No phone")}</p></TableCell><TableCell>{String(value(row, "invoice_number", "receipt_number", "receipt") || "—")}</TableCell><TableCell className="text-right">{formatMoney(value(row, "original_amount", "total", "amount"), currency)}</TableCell><TableCell className="text-right">{formatMoney(value(row, "paid_amount", "amount_paid"), currency)}</TableCell><TableCell className="text-right font-semibold">{formatMoney(value(row, "balance", "outstanding"), currency)}</TableCell><TableCell><p>{formatDateTime(value(row, "due_date", "due_at"))}</p><p className="text-xs text-muted-foreground">Created {formatDateTime(value(row, "created_at", "date"))}</p></TableCell><TableCell><Badge variant={statusVariant(rowStatus)}>{String(rowStatus)}</Badge></TableCell></TableRow>;
              })}</TableBody>
            </Table>
          ) : (
            <Table><TableHeader><TableRow><TableHead>Date / time</TableHead><TableHead>Payer / customer</TableHead><TableHead>Receipt / invoice</TableHead><TableHead>Method</TableHead><TableHead>Cashier</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((row, index) => <TableRow key={String(value(row, "id", "source_id") || index)}><TableCell className="whitespace-nowrap">{formatDateTime(value(row, "paid_at", "created_at", "date"))}</TableCell><TableCell><p className="font-medium">{String(value(row, "payer_name", "customer_name", "party_name") || "Unknown")}</p><p className="text-xs text-muted-foreground">{String(value(row, "payer_phone", "customer_phone", "phone") || "")}</p></TableCell><TableCell>{String(value(row, "invoice_number", "receipt_number", "receipt") || "—")}</TableCell><TableCell>{String(value(row, "payment_method", "method") || "—")}</TableCell><TableCell>{String(value(row, "cashier_name", "cashier") || "—")}</TableCell><TableCell className="text-right font-semibold">{formatMoney(value(row, "amount", "paid_amount"), currency)}</TableCell></TableRow>)}</TableBody>
            </Table>
          )}
          <ReportPagination {...pagination} onPage={setPage} />
        </ReportState>
      </Card>
    </div>
  );
}
