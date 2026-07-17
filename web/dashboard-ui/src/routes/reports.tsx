import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, CalendarRange } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Button, Card, SectionTitle, Select, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { addDaysISO, KES, todayISO } from "@/lib/format";

export const Route = createFileRoute("/reports")({
  component: Reports,
});

const TABS = ["Sales List", "Top Products", "By Payment"] as const;

function rangeForPreset(preset: string): { start: string; end: string } {
  const end = todayISO();
  if (preset === "Yesterday") {
    const y = addDaysISO(-1);
    return { start: y, end: y };
  }
  if (preset === "This Week") return { start: addDaysISO(-6), end };
  if (preset === "This Month") {
    const d = new Date();
    const start = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
    return { start, end };
  }
  return { start: end, end };
}

function Reports() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Sales List");
  const [preset, setPreset] = useState("Today");
  const range = useMemo(() => rangeForPreset(preset), [preset]);

  const summaryQ = useQuery({
    queryKey: ["reports-summary", range.start, range.end],
    queryFn: () => GET<any>("/reports/summary", { start: range.start, end: range.end }),
  });
  const salesQ = useQuery({
    queryKey: ["sales", range.start, range.end],
    queryFn: () => GET<any[]>("/sales", { start: range.start, end: range.end }),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";

  const data = summaryQ.data || {};
  const summary = data.summary || {};
  const topProducts = Array.isArray(data.top_products) ? data.top_products : [];
  const byPayment = Array.isArray(data.by_payment) ? data.by_payment : [];
  const hourly = Array.isArray(data.hourly) ? data.hourly : [];
  const sales = Array.isArray(salesQ.data) ? salesQ.data : [];

  const payTotal = byPayment.reduce((s: number, p: any) => s + Number(p.total || 0), 0) || 1;
  const maxHourly = Math.max(1, ...hourly.map((h: any) => Number(h.total || 0)));

  return (
    <AppShell title="Reports">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {["Today", "Yesterday", "This Week", "This Month"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
          <span className="text-xs text-text2 inline-flex items-center gap-1">
            <CalendarRange className="h-3.5 w-3.5" />
            {range.start} → {range.end}
          </span>
        </div>
        <a
          href={`/api/reports/html?date=${todayISO()}`}
          className="inline-flex"
          download
        >
          <Button variant="primary">
            <Download className="h-4 w-4" /> Download HTML Report
          </Button>
        </a>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="p-5 lg:col-span-2">
          <SectionTitle>
            Sales — {KES(summary.total_revenue || 0, currency)} ·{" "}
            {Number(summary.total_transactions || 0)} txns
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
          <SectionTitle>By Payment</SectionTitle>
          <ul className="space-y-3 text-sm">
            {byPayment.length === 0 ? (
              <li className="text-text2">No sales in range</li>
            ) : (
              byPayment.map((r: any) => {
                const pct = Math.round((Number(r.total || 0) / payTotal) * 100);
                return (
                  <li key={r.payment_method}>
                    <div className="flex justify-between text-text2 mb-1">
                      <span className="capitalize">{r.payment_method || "cash"}</span>
                      <span className="text-text font-semibold">
                        {pct}% · {KES(r.total, currency)}
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

      <div className="flex gap-1 bg-panel/60 border border-border rounded-lg p-1 mb-3 w-fit">
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
        {tab === "Top Products" ? (
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
        ) : (
          <Table head={["Receipt", "Time", "Cashier", "Total", "Status"]}>
            {sales.map((r: any) => (
              <tr key={r.id || r.receipt_number}>
                <td className="px-4 py-2.5 font-mono text-text">{r.receipt_number}</td>
                <td className="px-4 py-2.5 text-text2 tabular-nums">
                  {(r.created_at || "").slice(11, 16)}
                </td>
                <td className="px-4 py-2.5 text-text">{r.cashier_name}</td>
                <td className="px-4 py-2.5 font-semibold text-text tabular-nums">
                  {KES(r.total, currency)}
                </td>
                <td className="px-4 py-2.5 text-text2">{r.status || "completed"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </AppShell>
  );
}
