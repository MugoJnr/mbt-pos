import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Download,
  CalendarRange,
  BarChart3,
  Printer,
  FileSpreadsheet,
  FileText,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { SaleReceiptDialog } from "@/components/sale-receipt-dialog";
import {
  Button,
  Card,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Table,
} from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { downloadApiPost, exportQuery } from "@/lib/download";
import { ExportLockDialog } from "@/components/export-lock-dialog";
import { KES, localISO, rangeForPreset } from "@/lib/format";

export const Route = createFileRoute("/reports")({
  component: Reports,
});

const TABS = ["Sales List", "Top Products", "By Payment", "By Cashier"] as const;

function Reports() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Sales List");
  const [preset, setPreset] = useState("Today");
  const [customStart, setCustomStart] = useState(localISO());
  const [customEnd, setCustomEnd] = useState(localISO());
  const [employee, setEmployee] = useState("");
  const [payment, setPayment] = useState("");
  const [category, setCategory] = useState("");
  const [customer, setCustomer] = useState("");
  const [q, setQ] = useState("");
  const [exporting, setExporting] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"created_at" | "total" | "receipt_number">(
    "created_at",
  );
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [openSaleId, setOpenSaleId] = useState<number | null>(null);
  const [lockFormat, setLockFormat] = useState<string | null>(null);
  const [lockError, setLockError] = useState("");
  const sectionOptions = [
    ["sales", "Sales"],
    ["debt", "Debt"],
    ["inventory", "Inventory"],
    ["out_of_stock", "Out of stock"],
    ["low_stock", "Low stock"],
    ["variance", "Payment variance"],
  ] as const;
  const [sections, setSections] = useState<string[]>(sectionOptions.map((item) => item[0]));
  const pageSize = 25;

  const range = useMemo(() => {
    if (preset === "Custom" || preset === "Choose a day") {
      const end = preset === "Choose a day" ? customStart : customEnd;
      return { start: customStart, end: end < customStart ? customStart : end };
    }
    return rangeForPreset(preset);
  }, [preset, customStart, customEnd]);

  const filterParams = useMemo(
    () => ({
      start: range.start,
      end: range.end,
      employee: employee || undefined,
      payment: payment || undefined,
      category: category || undefined,
      customer: customer || undefined,
      q: q || undefined,
    }),
    [range, employee, payment, category, customer, q],
  );

  const dataQ = useQuery({
    queryKey: ["reports-data", filterParams],
    queryFn: () =>
      GET<any>("/reports/data", {
        start: filterParams.start,
        end: filterParams.end,
        ...(filterParams.employee ? { employee: filterParams.employee } : {}),
        ...(filterParams.payment ? { payment: filterParams.payment } : {}),
        ...(filterParams.category ? { category: filterParams.category } : {}),
        ...(filterParams.customer ? { customer: filterParams.customer } : {}),
        ...(filterParams.q ? { q: filterParams.q } : {}),
      }),
  });

  const data = dataQ.data || {};
  const summary = data.summary || {};
  const topProducts = Array.isArray(data.top_products) ? data.top_products : [];
  const byPayment = Array.isArray(data.by_payment) ? data.by_payment : [];
  const collectedMethods = Array.isArray(data.collected_methods) ? data.collected_methods : [];
  const hourly = Array.isArray(data.hourly) ? data.hourly : [];
  const cashiers = Array.isArray(data.cashiers) ? data.cashiers : [];
  const sales = Array.isArray(data.sales) ? data.sales : [];
  const meta = data.meta || {};
  const currency = data.currency || "KES";

  const payTotal = collectedMethods
    .filter((p: any) => p.method !== "Credit issued")
    .reduce((s: number, p: any) => s + Number(p.collected || 0), 0) || 1;
  const maxHourly = Math.max(1, ...hourly.map((h: any) => Number(h.total || 0)));

  const sortedSales = useMemo(() => {
    const arr = [...sales];
    arr.sort((a, b) => {
      let av: any = a[sortKey];
      let bv: any = b[sortKey];
      if (sortKey === "total") {
        av = Number(av || 0);
        bv = Number(bv || 0);
      } else {
        av = String(av || "");
        bv = String(bv || "");
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
  }, [sales, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(sortedSales.length / pageSize));
  const pageRows = sortedSales.slice(page * pageSize, page * pageSize + pageSize);

  async function doExport(format: string, password: string) {
    try {
      setExporting(format);
      setLockError("");
      const ext = format === "csv" ? "zip" : format;
      if (!sections.length) {
        setLockError("Select at least one section.");
        return;
      }
      await downloadApiPost(
        "/reports/export",
        { ...filterParams, format, password, confirm: password, sections },
        `MBT_Sales.${ext}`,
      );
      setLockFormat(null);
      toast.success(format === "csv" ? "Encrypted ZIP downloaded" : `${format.toUpperCase()} encrypted and downloaded`);
    } catch (e: any) {
      setLockError(e?.message || "Export failed");
    } finally {
      setExporting(null);
    }
  }

  function printReport() {
    const ok = window.confirm(
      "A printed page is not encrypted. Anyone who can see the paper can read the report. Continue?",
    );
    if (!ok) return;
    const qs = exportQuery({ ...filterParams, format: "html", print: "1" });
    window.open(`/api/reports/export?${qs}`, "_blank");
  }

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "total" ? "desc" : "desc");
    }
    setPage(0);
  }

  return (
    <AppShell title="Reports">
      <ExportLockDialog
        open={lockFormat != null}
        kind={lockFormat === "csv" ? "CSV" : lockFormat === "pdf" ? "PDF" : "Excel workbook"}
        busy={!!exporting}
        error={lockError}
        onCancel={() => {
          if (!exporting) setLockFormat(null);
        }}
        onConfirm={(password) => {
          if (lockFormat) void doExport(lockFormat, password);
        }}
      />
      <PageHeader
        eyebrow="Operations"
        title="Reports"
        icon={<BarChart3 className="h-4 w-4" />}
        description={`${range.start} → ${range.end}${data.sales_total != null ? ` · ${data.sales_total} sales` : ""}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              className="min-h-[44px]"
              disabled={!!exporting}
              onClick={() => {
                setLockError("");
                setLockFormat("xlsx");
              }}
            >
              <FileSpreadsheet className="h-4 w-4" /> Excel
            </Button>
            <Button
              variant="secondary"
              className="min-h-[44px]"
              disabled={!!exporting}
              onClick={() => {
                setLockError("");
                setLockFormat("csv");
              }}
            >
              <Download className="h-4 w-4" /> CSV
            </Button>
            <Button
              variant="secondary"
              className="min-h-[44px]"
              disabled={!!exporting}
              onClick={() => {
                setLockError("");
                setLockFormat("pdf");
              }}
            >
              <FileText className="h-4 w-4" /> PDF
            </Button>
            <Button
              variant="primary"
              className="min-h-[44px]"
              disabled={!!exporting}
              onClick={printReport}
            >
              <Printer className="h-4 w-4" /> Print
            </Button>
          </div>
        }
      />

      <Card className="p-4 mb-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-3">
          <label className="block text-xs font-semibold text-text2">
            Period
            <Select
              value={preset}
              onChange={(e) => {
                setPreset(e.target.value);
                setPage(0);
              }}
              className="mt-1 min-h-[44px]"
            >
              {["Today", "Yesterday", "Choose a day", "This Week", "Last Week", "This Month", "Last Month", "This Year", "Custom"].map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
          </label>
          {preset === "Custom" || preset === "Choose a day" ? (
            <>
              <label className="block text-xs font-semibold text-text2">
                {preset === "Choose a day" ? "Day" : "Start"}
                <Input
                  type="date"
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                  className="mt-1 min-h-[44px]"
                />
              </label>
              {preset === "Custom" ? (
              <label className="block text-xs font-semibold text-text2">
                End
                <Input
                  type="date"
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                  className="mt-1 min-h-[44px]"
                />
              </label>
              ) : null}
            </>
          ) : (
            <div className="text-xs text-text2 flex items-end gap-1 pb-3">
              <CalendarRange className="h-3.5 w-3.5" />
              {range.start} → {range.end}
            </div>
          )}
          <label className="block text-xs font-semibold text-text2">
            Employee
            <Select
              value={employee}
              onChange={(e) => {
                setEmployee(e.target.value);
                setPage(0);
              }}
              className="mt-1 min-h-[44px]"
            >
              <option value="">All</option>
              {(meta.employees || []).map((n: string) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
          <label className="block text-xs font-semibold text-text2">
            Payment
            <Select
              value={payment}
              onChange={(e) => {
                setPayment(e.target.value);
                setPage(0);
              }}
              className="mt-1 min-h-[44px]"
            >
              <option value="">All</option>
              {(meta.payment_methods || []).map((n: string) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
          <label className="block text-xs font-semibold text-text2">
            Category
            <Select
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(0);
              }}
              className="mt-1 min-h-[44px]"
            >
              <option value="">All</option>
              {(meta.categories || []).map((n: string) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
          <label className="block text-xs font-semibold text-text2">
            Customer
            <Input
              value={customer}
              onChange={(e) => {
                setCustomer(e.target.value);
                setPage(0);
              }}
              placeholder="Name or phone"
              className="mt-1 min-h-[44px]"
            />
          </label>
          <label className="block text-xs font-semibold text-text2 sm:col-span-2">
            Search receipts
            <Input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(0);
              }}
              placeholder="Receipt # or cashier…"
              className="mt-1 min-h-[44px]"
            />
          </label>
        </div>
      </Card>

      <Card className="mb-4 p-4">
        <div className="mb-2 text-xs font-semibold text-text2">
          Include in the file · {sections.length} selected
        </div>
        <div className="flex flex-wrap gap-3">
          {sectionOptions.map(([key, label]) => (
            <label key={key} className="flex min-h-[36px] items-center gap-2 text-sm text-text">
              <input
                type="checkbox"
                checked={sections.includes(key)}
                onChange={(e) => {
                  setSections((current) =>
                    e.target.checked ? [...current, key] : current.filter((item) => item !== key),
                  );
                }}
              />
              {label}
            </label>
          ))}
          <button
            type="button"
            className="text-sm font-semibold text-gold"
            onClick={() => setSections(sectionOptions.map((item) => item[0]))}
          >
            All
          </button>
          <button
            type="button"
            className="text-sm font-semibold text-text2"
            onClick={() => setSections([])}
          >
            Clear
          </button>
        </div>
        <p className="mt-2 text-xs text-text2">
          Excel and PDF use this choice. Out of stock is only products with zero quantity. It is not the full inventory list.
        </p>
      </Card>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <Card className="p-4">
          <div className="text-xs font-semibold text-text2">Sale value</div>
          <div className="mt-1 text-xl font-bold">{KES(summary.sales_value ?? summary.total_revenue ?? 0, currency)}</div>
          <div className="mt-1 text-xs text-text2">What was sold. This is not cash in the drawer.</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-text2">Money collected</div>
          <div className="mt-1 text-xl font-bold">{KES(summary.collected ?? 0, currency)}</div>
          <div className="mt-1 text-xs text-text2">
            Cash {KES(summary.cash_collected ?? 0, currency)} · M-Pesa {KES(summary.mpesa_collected ?? 0, currency)} · Card {KES(summary.card_collected ?? 0, currency)} · Bank {KES(summary.bank_collected ?? 0, currency)}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-text2">Credit issued</div>
          <div className="mt-1 text-xl font-bold">{KES(summary.credit_issued ?? 0, currency)}</div>
          <div className="mt-1 text-xs text-text2">Left unpaid on these sales. A later repayment is not a new sale.</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs font-semibold text-text2">Gross profit</div>
          <div className="mt-1 text-xl font-bold">
            {summary.profit == null ? "—" : KES(summary.profit, currency)}
          </div>
          <div className="mt-1 text-xs text-text2">
            {Number(summary.uncosted_lines || 0) > 0
              ? `${summary.uncosted_lines} lines have no cost, so this profit is incomplete.`
              : "Sale value minus the cost recorded on the lines. This is not net profit."}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-5 lg:col-span-2">
          <SectionTitle>
            Sales — {KES(summary.total_revenue || 0, currency)} ·{" "}
            {Number(summary.total_transactions || 0)} txns
            {summary.avg_transaction != null ? (
              <span className="text-text2 font-normal text-sm">
                {" "}
                · avg {KES(summary.avg_transaction, currency)}
              </span>
            ) : null}
          </SectionTitle>
          <div className="flex items-end gap-1.5 h-24 mt-2">
            {hourly.length === 0 ? (
              <div className="text-sm text-text2 py-8 w-full text-center">No hourly data</div>
            ) : (
              hourly.map((h: any) => (
                <div
                  key={h.hour}
                  title={`${h.hour}:00 — ${KES(h.total, currency)}`}
                  style={{ height: `${(Number(h.total) / maxHourly) * 100}%` }}
                  className="flex-1 rounded-t bg-gradient-to-t from-gold/40 to-gold min-h-[4px]"
                />
              ))
            )}
          </div>
        </Card>
        <Card className="p-5">
          <SectionTitle>Money collected by method</SectionTitle>
          <p className="mb-2 text-xs text-text2">
            A split sale is divided across the methods used. Credit issued is shown separately and is not cash.
          </p>
          <ul className="space-y-3 text-sm">
            {collectedMethods.length === 0 ? (
              <li className="text-text2">No sales in range</li>
            ) : (
              collectedMethods.map((r: any) => {
                const pct = Math.min(100, Math.round((Number(r.collected || 0) / payTotal) * 100));
                return (
                  <li key={r.method}>
                    <div className="flex justify-between text-text2 mb-1">
                      <span>{r.method}</span>
                      <span className="text-text font-semibold">
                        {pct}% · {KES(r.collected, currency)}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-panel overflow-hidden">
                      <div style={{ width: `${pct}%` }} className="h-full bg-gold" />
                    </div>
                  </li>
                );
              })
            )}
          </ul>
        </Card>
      </div>

      <div className="flex gap-1 bg-panel/60 border border-border rounded-lg p-1 mb-3 w-fit flex-wrap">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
              tab === t ? "bg-gold text-[color:var(--gold-fg)]" : "text-text2 hover:text-text"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <Card>
        {dataQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading report…</div>
        ) : tab === "Top Products" ? (
          <Table head={["Product", "Qty Sold", "Revenue"]}>
            {topProducts.map((p: any) => (
              <tr key={p.product_name}>
                <td className="px-4 py-2.5 text-text font-medium">{p.product_name}</td>
                <td className="px-4 py-2.5 tabular-nums text-text2">{p.qty_sold}</td>
                <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                  {KES(p.revenue, currency)}
                </td>
              </tr>
            ))}
          </Table>
        ) : tab === "By Payment" ? (
          <Table head={["Method", "Count", "Total"]}>
            {byPayment.map((p: any) => (
              <tr key={p.payment_method}>
                <td className="px-4 py-2.5 capitalize text-text">{p.payment_method}</td>
                <td className="px-4 py-2.5 tabular-nums text-text2">{p.count}</td>
                <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                  {KES(p.total, currency)}
                </td>
              </tr>
            ))}
          </Table>
        ) : tab === "By Cashier" ? (
          <Table head={["Cashier", "Count", "Total"]}>
            {cashiers.map((p: any) => (
              <tr key={p.cashier_name}>
                <td className="px-4 py-2.5 text-text">{p.cashier_name}</td>
                <td className="px-4 py-2.5 tabular-nums text-text2">{p.count}</td>
                <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                  {KES(p.total, currency)}
                </td>
              </tr>
            ))}
          </Table>
        ) : (
          <>
            <Table
              head={[
                <button key="r" type="button" onClick={() => toggleSort("receipt_number")}>
                  Receipt {sortKey === "receipt_number" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </button>,
                <button key="t" type="button" onClick={() => toggleSort("created_at")}>
                  Time {sortKey === "created_at" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </button>,
                "Cashier",
                "Pay",
                <button key="tot" type="button" onClick={() => toggleSort("total")}>
                  Total {sortKey === "total" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </button>,
                "Status",
              ]}
            >
              {pageRows.map((r: any) => (
                <tr key={r.id || r.receipt_number}>
                  <td className="px-4 py-2.5 font-mono text-text">
                    <button
                      type="button"
                      className="font-semibold text-gold hover:underline"
                      onClick={() => setOpenSaleId(Number(r.id))}
                    >
                      {r.receipt_number}
                    </button>
                  </td>
                  <td className="px-4 py-2.5 text-text2 tabular-nums">
                    {(r.created_at || "").slice(0, 16)}
                  </td>
                  <td className="px-4 py-2.5 text-text">{r.cashier_name}</td>
                  <td className="px-4 py-2.5 text-text2 capitalize">{r.payment_method || "—"}</td>
                  <td className="px-4 py-2.5 font-semibold text-text tabular-nums">
                    {KES(r.total, currency)}
                  </td>
                  <td className="px-4 py-2.5 text-text2">{r.status || "completed"}</td>
                </tr>
              ))}
            </Table>
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-border text-xs text-text2">
              <span>
                Page {page + 1} / {pageCount} · {sortedSales.length} rows
                {data.sales_truncated ? " (export for full set)" : ""}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={page <= 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
      <SaleReceiptDialog saleId={openSaleId} currency={currency} onClose={() => setOpenSaleId(null)} />
    </AppShell>
  );
}
