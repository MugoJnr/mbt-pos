import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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

const AGE_LABELS = [
  ["current", "Current"],
  ["days_1_30", "1–30 days"],
  ["days_31_60", "31–60 days"],
  ["days_61_90", "61–90 days"],
  ["days_90_plus", "Over 90 days"],
] as const;

export function DebtsPanel({ orgId, start, end, age, record }: { orgId: string; start: string; end: string; age?: string; record?: { kind: "debt" | "payment"; device: string; source: string } }) {
  const [view, setView] = useState("invoices");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState<AnalyticsRow | null>(null);
  const [bucket, setBucket] = useState(age || "");
  const [missing, setMissing] = useState("");
  useEffect(() => setBucket(age || ""), [age]);
  useEffect(() => setPage(1), [view, search, status, start, end, bucket]);
  const params = bucket
    ? { org_id: orgId, page: String(page), page_size: "25", search, status, age: bucket }
    : { org_id: orgId, start, end, page: String(page), page_size: "25", search, status };
  const ageingQ = useQuery({
    queryKey: ["cloud-debt-ageing", orgId],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/debt-ageing", { org_id: orgId }),
    enabled: Boolean(orgId),
  });
  const ageing = ((ageingQ.data?.ageing || {}) as AnalyticsRow);
  const ageingDetail = (ageing.detail || {}) as Record<string, AnalyticsRow>;
  const linkedPath = record?.device && record.source
    ? `/cloud/analytics/${record.kind === "payment" ? "debt-payments" : "debts"}/${encodeURIComponent(record.device)}/${encodeURIComponent(record.source)}`
    : "";
  const linkedQ = useQuery({
    queryKey: ["cloud-linked-debt", linkedPath, orgId],
    queryFn: () => GET<AnalyticsResponse>(linkedPath, { org_id: orgId }),
    enabled: Boolean(linkedPath),
  });
  useEffect(() => {
    if (!record?.source) return;
    const row = (linkedQ.data?.debt || linkedQ.data?.payment) as AnalyticsRow | undefined;
    if (row) {
      setSelected(row);
      setMissing("");
    } else if (linkedQ.data?.error || linkedQ.isError) {
      setMissing("That debt record is not in the synced copy.");
    }
  }, [record?.source, linkedQ.data, linkedQ.isError]);
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
      {missing ? <p className="rounded-lg border px-3 py-2 text-sm">{missing}</p> : null}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {AGE_LABELS.map(([key, label]) => {
          const item = ageingDetail[key] || {};
          const active = bucket === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setBucket(active ? "" : key)}
              className={`rounded-xl border p-3 text-left ${active ? "border-primary bg-primary/5" : "border-border"}`}
            >
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-semibold">{formatMoney(item.amount ?? ageing[key], currency)}</p>
              <p className="text-xs text-muted-foreground">{String(item.customers ?? 0)} customers · {String(item.share ?? 0)}%</p>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">Ageing covers every open debt. Current means not yet due. A selected bucket is not limited to the sales dates above.</p>
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
                return <TableRow key={String(value(row, "id", "source_id", "invoice_number") || index)} className="cursor-pointer" onClick={() => setSelected(row)}><TableCell><p className="font-medium">{String(value(row, "party_name", "customer_name", "name") || "Unknown")}</p><p className="text-xs text-muted-foreground">{String(value(row, "party_phone", "customer_phone", "phone") || "No phone")}</p></TableCell><TableCell>{String(value(row, "invoice_number", "receipt_number", "receipt") || "—")}</TableCell><TableCell className="text-right">{formatMoney(value(row, "original_amount", "total", "amount"), currency)}</TableCell><TableCell className="text-right">{formatMoney(value(row, "paid_amount", "amount_paid"), currency)}</TableCell><TableCell className="text-right font-semibold">{formatMoney(value(row, "balance", "outstanding"), currency)}</TableCell><TableCell><p>{formatDateTime(value(row, "due_date", "due_at"))}</p><p className="text-xs text-muted-foreground">Created {formatDateTime(value(row, "created_at", "date"))}</p></TableCell><TableCell><Badge variant={statusVariant(rowStatus)}>{String(rowStatus)}</Badge></TableCell></TableRow>;
              })}</TableBody>
            </Table>
          ) : (
            <Table><TableHeader><TableRow><TableHead>Date / time</TableHead><TableHead>Payer / customer</TableHead><TableHead>Receipt / invoice</TableHead><TableHead>Method</TableHead><TableHead>Cashier</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((row, index) => <TableRow key={String(value(row, "id", "source_id") || index)} className="cursor-pointer" onClick={() => setSelected(row)}><TableCell className="whitespace-nowrap">{formatDateTime(value(row, "paid_at", "created_at", "date"))}</TableCell><TableCell><p className="font-medium">{String(value(row, "payer_name", "customer_name", "party_name") || "Unknown")}</p><p className="text-xs text-muted-foreground">{String(value(row, "payer_phone", "customer_phone", "phone") || "")}</p></TableCell><TableCell>{String(value(row, "invoice_number", "receipt_number", "receipt") || "—")}</TableCell><TableCell>{String(value(row, "payment_method", "method") || "—")}</TableCell><TableCell>{String(value(row, "cashier_name", "cashier") || "—")}</TableCell><TableCell className="text-right font-semibold">{formatMoney(value(row, "amount", "paid_amount"), currency)}</TableCell></TableRow>)}</TableBody>
            </Table>
          )}
          <ReportPagination {...pagination} onPage={setPage} />
        </ReportState>
      </Card>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{view === "payments" ? "Repayment" : "Debt invoice"}</DialogTitle>
            <DialogDescription>
              {String(value(selected || {}, "customer_name", "party_name") || "Customer")}
              {value(selected || {}, "customer_phone") ? ` · ${String(value(selected || {}, "customer_phone"))}` : ""}
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <div className="space-y-3 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <p>Receipt / invoice: {String(value(selected, "invoice_number", "receipt_number", "payment_receipt") || "—")}</p>
                <p>Status: {String(value(selected, "debt_status", "status") || "—")}</p>
                <p>Original: {formatMoney(value(selected, "original_amount", "total_amount", "total", "amount"), currency)}</p>
                <p>Paid: {formatMoney(value(selected, "paid_amount", "amount_paid", "amount"), currency)}</p>
                <p>Balance: {formatMoney(value(selected, "balance", "outstanding"), currency)}</p>
                <p>Due: {formatDateTime(value(selected, "due_date"))}</p>
                <p>Age bucket: {String(value(selected, "age_bucket") || "—")}</p>
                <p>Last payment: {Array.isArray(selected.payments) && (selected.payments as AnalyticsRow[]).length ? formatDateTime(value((selected.payments as AnalyticsRow[])[(selected.payments as AnalyticsRow[]).length - 1], "source_created_at")) : "—"}</p>
                <p>Method: {String(value(selected, "payment_method") || "—")}</p>
                <p>Cashier: {String(value(selected, "cashier_name") || "—")}</p>
              </div>
              {Array.isArray(selected.payments) ? (
                <Table>
                  <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Method</TableHead><TableHead>Cashier</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
                  <TableBody>{(selected.payments as AnalyticsRow[]).map((pay, index) => (
                    <TableRow key={index}>
                      <TableCell>{formatDateTime(value(pay, "source_created_at", "created_at"))}</TableCell>
                      <TableCell>{String(value(pay, "payment_method") || "—")}</TableCell>
                      <TableCell>{String(value(pay, "cashier_name") || "—")}</TableCell>
                      <TableCell className="text-right">{formatMoney(value(pay, "amount"), currency)}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              ) : null}
              <p className="text-xs text-muted-foreground">Read-only. Recording a payment stays on the till.</p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
