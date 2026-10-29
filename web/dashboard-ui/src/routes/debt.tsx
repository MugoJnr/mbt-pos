import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Phone, Receipt, Banknote, Users, AlertTriangle, TrendingDown } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, KpiCard, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/debt")({
  component: Debt,
});

const TABS = ["Overview", "Invoices", "Customers", "Payments"] as const;

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Debt() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [payId, setPayId] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("Cash");
  const [payDate, setPayDate] = useState(localToday());
  const [payError, setPayError] = useState("");
  const [payNote, setPayNote] = useState("");
  const [query, setQuery] = useState("");

  const summaryQ = useQuery({
    queryKey: ["debt-summary"],
    queryFn: () => GET<any>("/debt/summary"),
  });
  const invoicesQ = useQuery({
    queryKey: ["debt-invoices"],
    queryFn: () => GET<any[]>("/debt/invoices"),
    enabled: tab === "Invoices" || tab === "Overview",
  });
  const customersQ = useQuery({
    queryKey: ["customers"],
    queryFn: () => GET<any[]>("/customers"),
    enabled: tab === "Customers" || tab === "Overview",
  });
  const paymentsQ = useQuery({
    queryKey: ["debt-payments"],
    queryFn: () => GET<any[]>("/debt/payments"),
    enabled: tab === "Payments",
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";

  const ds = summaryQ.data || {};
  const outstanding = Number(ds.outstanding?.total ?? 0);
  const overdueCnt = Number(ds.overdue?.count ?? 0);
  const customersWithDebt = Number(ds.customers_with_debt ?? 0);
  const topDebtors = Array.isArray(ds.top_debtors) ? ds.top_debtors : [];
  const largest = topDebtors[0];

  const invoices = (Array.isArray(invoicesQ.data) ? invoicesQ.data : []).filter((inv) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return [inv.invoice_number, inv.customer_name, inv.receipt_number, inv.status, inv.phone]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  const payToken = useRef("");
  async function collect() {
    setPayError("");
    const amount = Number(payAmount);
    if (!payId) return setPayError("Choose an open invoice.");
    if (!Number.isFinite(amount) || amount <= 0) return setPayError("Payment must be greater than zero.");
    if (payDate > localToday()) return setPayError("Future payment dates are not allowed.");
    if (!payToken.current) payToken.current = crypto.randomUUID();
    const res = await POST<any>(`/debt/invoices/${payId}/pay`, {
      amount,
      payment_method: payMethod,
      payment_date: payDate,
      payment_reference: payToken.current,
    });
    if (!res || res.error) {
      setPayError(res?.error || "Payment was not recorded.");
      return;
    }
    payToken.current = "";
    setPayAmount("");
    setPayNote(
      res.duplicate
        ? `Already recorded. Balance ${KES(res.balance_after, currency)}.`
        : `Recorded. Balance ${KES(res.balance_after, currency)}.`,
    );
    await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    await qc.invalidateQueries({ queryKey: ["debt-summary"] });
    await qc.invalidateQueries({ queryKey: ["debt-payments"] });
  }
  const customers = Array.isArray(customersQ.data) ? customersQ.data : [];
  const payments = Array.isArray(paymentsQ.data) ? paymentsQ.data : [];

  const openInvoices = (Array.isArray(invoicesQ.data) ? invoicesQ.data : []).filter(
    (inv) => Number(inv.balance) > 0 && inv.status !== "cancelled" && inv.status !== "paid",
  );
  const debtCustomers = [...openInvoices.reduce((map: Map<number, any>, inv: any) => {
    const current = map.get(inv.customer_id) || {
      id: inv.customer_id,
      name: inv.customer_name,
      phone: inv.c_phone || inv.phone,
      total_outstanding: 0,
      open_invoices: 0,
    };
    current.total_outstanding = Math.round((current.total_outstanding + Number(inv.balance)) * 100) / 100;
    current.open_invoices += 1;
    map.set(inv.customer_id, current);
    return map;
  }, new Map()).values()].sort((a, b) => b.total_outstanding - a.total_outstanding);

  return (
    <AppShell title="Debt Management">
      <PageHeader
        eyebrow="Operations"
        title="Debt Management"
        description="A credit sale creates the debt. A repayment collects money already owed and is not a new sale. Outstanding is what remains."
      />
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1 bg-panel/60 border border-border rounded-lg p-1">
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
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KpiCard
          label="Total Outstanding"
          value={KES(outstanding, currency)}
          sub="all customers"
          accent="err"
          icon={<Banknote className="h-5 w-5" />}
        />
        <KpiCard
          label="Customers w/ Debt"
          value={String(customersWithDebt)}
          sub="active accounts"
          accent="warn"
          icon={<Users className="h-5 w-5" />}
        />
        <KpiCard
          label="Overdue"
          value={String(overdueCnt)}
          sub="past due"
          accent="err"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
        <KpiCard
          label="Largest Debtor"
          value={largest ? KES(largest.total_balance, currency) : KES(0, currency)}
          sub={largest?.customer_name || "—"}
          accent="info"
          icon={<TrendingDown className="h-5 w-5" />}
        />
      </div>

      <Card>
        <div className="p-4 border-b border-border">
          <SectionTitle>
            {tab === "Overview"
              ? "Customer Debts"
              : tab === "Invoices"
                ? "Invoices"
                : tab === "Customers"
                  ? "Customers"
                  : "Payments"}
          </SectionTitle>
        </div>

        {tab === "Overview" || tab === "Customers" ? (
          <Table head={["Customer", "Phone", "Outstanding", "Open Invoices", "Actions"]}>
            {(tab === "Overview" ? debtCustomers : customers).map((c: any) => (
              <tr key={c.id}>
                <td className="px-4 py-2.5 text-text font-medium">{c.name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text2">{c.phone || "—"}</td>
                <td className="px-4 py-2.5 tabular-nums text-err font-semibold">
                  {c.total_outstanding == null ? "—" : KES(c.total_outstanding || 0, currency)}
                </td>
                <td className="px-4 py-2.5 text-text2">{c.open_invoices ?? "—"}</td>
                <td className="px-4 py-2.5">
                  {c.phone ? (
                    <a
                      href={`tel:${c.phone}`}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-text2 hover:text-gold hover:bg-hover"
                    >
                      <Phone className="h-3.5 w-3.5" />
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </Table>
        ) : null}

        {tab === "Invoices" ? (
          <div className="p-4 border-b border-border grid grid-cols-1 md:grid-cols-5 gap-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search customer, invoice, status" />
            <select className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={payId} onChange={(e) => setPayId(e.target.value)}>
              <option value="">Open invoice</option>
              {openInvoices.map((inv) => (
                <option key={inv.id} value={inv.id}>{inv.invoice_number} · {inv.customer_name} · {KES(inv.balance, currency)}</option>
              ))}
            </select>
            <Input value={payAmount} onChange={(e) => setPayAmount(e.target.value)} placeholder="Amount" />
            <select className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={payMethod} onChange={(e) => setPayMethod(e.target.value)}>
              {["Cash", "M-Pesa", "Bank"].map((m) => <option key={m}>{m}</option>)}
            </select>
            <Input type="date" aria-label="Payment date" value={localToday()} readOnly />
            <Button onClick={collect}>Record payment</Button>
            {payError ? <p className="md:col-span-5 text-sm text-err">{payError}</p> : null}
            {payNote ? <p className="md:col-span-5 text-sm text-text">{payNote}</p> : null}
          </div>
        ) : null}

        {tab === "Invoices" ? (
          <Table head={["Invoice", "Receipt", "Customer", "Sale date", "Original", "Paid", "Outstanding", "Status", "Due"]}>
            {invoices.map((inv: any) => (
              <tr key={inv.id}>
                <td className="px-4 py-2.5 font-mono text-sm text-text">{inv.invoice_number}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text2">{inv.receipt_number || "—"}</td>
                <td className="px-4 py-2.5 text-text">{inv.customer_name}</td>
                <td className="px-4 py-2.5 text-text2">{inv.sale_date || (inv.created_at || "").slice(0, 10)}</td>
                <td className="px-4 py-2.5 tabular-nums">{KES(inv.total_amount, currency)}</td>
                <td className="px-4 py-2.5 tabular-nums">{KES(inv.amount_paid, currency)}</td>
                <td className="px-4 py-2.5 tabular-nums text-err font-semibold">
                  {KES(inv.balance, currency)}
                </td>
                <td className="px-4 py-2.5">
                  <Badge
                    tone={
                      inv.status === "paid"
                        ? "ok"
                        : inv.status === "partial"
                          ? "warn"
                          : "err"
                    }
                  >
                    {inv.status}
                  </Badge>
                </td>
                <td className="px-4 py-2.5 text-text2">{inv.due_date || "—"}</td>
              </tr>
            ))}
          </Table>
        ) : null}

        {tab === "Payments" ? (
          <Table head={["Receipt", "Customer", "Invoice", "Collected", "Balance after", "Method", "When"]}>
            {payments.map((p: any) => (
              <tr key={p.id}>
                <td className="px-4 py-2.5 font-mono text-sm">{p.payment_receipt}</td>
                <td className="px-4 py-2.5 text-text">{p.customer_name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.invoice_number}</td>
                <td className="px-4 py-2.5 tabular-nums text-ok font-semibold">
                  {KES(p.amount, currency)}
                </td>
                <td className="px-4 py-2.5 tabular-nums">{KES(p.balance_after, currency)}</td>
                <td className="px-4 py-2.5 text-text2">{p.payment_method}</td>
                <td className="px-4 py-2.5 text-text2 text-xs">
                  {(p.created_at || "").slice(0, 16)}
                </td>
              </tr>
            ))}
          </Table>
        ) : null}

        {((tab === "Overview" || tab === "Customers") && debtCustomers.length === 0 && tab === "Overview") ||
        (tab === "Invoices" && invoices.length === 0) ||
        (tab === "Payments" && payments.length === 0) ? (
          <div className="py-10 text-center text-sm text-text2 flex items-center justify-center gap-2">
            <Receipt className="h-4 w-4" /> No records yet
          </div>
        ) : null}
      </Card>
    </AppShell>
  );
}
