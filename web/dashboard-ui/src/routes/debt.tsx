import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Phone, Receipt, Banknote, Users, AlertTriangle, TrendingDown } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, KpiCard, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { DeliveryActions } from "@/components/delivery-actions";
import { GET, POST, getUser } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/debt")({
  component: Debt,
});

const TABS = ["Overview", "Invoices", "Customers", "Payments", "Supplier debts", "Resolution"] as const;

function allowed(action: string, fallback: boolean) {
  const list = getUser()?.effective_permissions;
  if (Array.isArray(list)) return list.map(String).includes(action);
  return fallback;
}

function canSeeSupplierDebts() {
  const role = String(getUser()?.role || "").toLowerCase();
  return allowed("supplier.view", ["viewer", "manager", "admin", "superadmin"].includes(role));
}

function canPaySupplier() {
  const role = String(getUser()?.role || "").toLowerCase();
  return allowed("supplier.pay", ["cashier", "manager", "admin", "superadmin"].includes(role));
}

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function CollectPanel({
  customerId,
  customerName,
  invoices,
  currency,
  onClose,
  onSaved,
}: {
  customerId: number;
  customerName: string;
  invoices: any[];
  currency: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const ordered = [...invoices].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) || Number(a.id) - Number(b.id));
  const owed = ordered.reduce((sum, inv) => sum + Number(inv.balance || 0), 0);
  const [amount, setAmount] = useState(String(owed || ""));
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [method, setMethod] = useState("cash");
  const [method2, setMethod2] = useState("");
  const [method2Amount, setMethod2Amount] = useState("");
  const [manual, setManual] = useState<Record<number, string>>({});
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const token = useRef("");
  if (!token.current) token.current = crypto.randomUUID();

  const methods = () => {
    const total = Number(amount);
    const second = Number(method2Amount || 0);
    if (method2 && second > 0) {
      return [
        { method, amount: Math.round((total - second) * 100) / 100 },
        { method: method2, amount: second },
      ];
    }
    return [{ method, amount: total }];
  };

  async function loadPreview() {
    const total = Number(amount);
    if (!Number.isFinite(total) || total <= 0) {
      setPreview(null);
      return;
    }
    const allocations = mode === "manual"
      ? ordered.filter((inv) => Number(manual[inv.id]) > 0).map((inv) => ({ invoice_id: inv.id, amount: Number(manual[inv.id]) }))
      : [];
    const res = await POST<any>(`/debt/customers/${customerId}/preview`, {
      amount: total,
      mode,
      allocations,
      methods: methods(),
    });
    if (!res || res.error) {
      setError(res?.error || "Could not preview this payment.");
      setPreview(null);
      return;
    }
    setError("");
    setPreview(res);
  }

  const invoiceKey = ordered.map((inv) => `${inv.id}:${inv.balance}`).join("|");
  useEffect(() => {
    const handle = window.setTimeout(() => { void loadPreview(); }, 200);
    return () => window.clearTimeout(handle);
    // Manual amounts are only part of the request when the cashier is choosing receipts.
  }, [amount, mode, method, method2, method2Amount, customerId, invoiceKey, mode === "manual" ? JSON.stringify(manual) : ""]);

  async function save() {
    if (busy) return;
    const total = Number(amount);
    if (!Number.isFinite(total) || total <= 0) {
      setError("Enter the amount received.");
      return;
    }
    setBusy(true);
    setError("");
    const allocations = mode === "manual"
      ? ordered.filter((inv) => Number(manual[inv.id]) > 0).map((inv) => ({ invoice_id: inv.id, amount: Number(manual[inv.id]) }))
      : [];
    const res = await POST<any>(`/debt/customers/${customerId}/collect`, {
      amount: total,
      mode,
      allocations,
      methods: methods(),
      client_token: token.current,
    });
    setBusy(false);
    if (!res || res.error) {
      setError(res?.error || "Payment was not recorded.");
      return;
    }
    setNote(`${res.collection_receipt}. Allocated ${KES(res.allocated, currency)}. Credit ${KES(res.unapplied, currency)}.`);
    setAmount("");
    setPreview(null);
    setManual({});
    token.current = crypto.randomUUID();
    await onSaved();
  }

  const lines = preview?.lines || ordered.map((inv) => ({
    invoice_id: inv.id,
    invoice_number: inv.invoice_number,
    receipt_number: inv.receipt_number,
    created_at: inv.created_at,
    original: inv.total_amount,
    paid: inv.amount_paid,
    outstanding: inv.balance,
    allocate: 0,
    remaining: inv.balance,
  }));

  return (
    <div className="border-t border-border p-4">
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Receive payment — {customerName}</SectionTitle>
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-5">
        <Input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" aria-label="Amount received" />
        <select className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={mode} onChange={(e) => setMode(e.target.value as "auto" | "manual")} aria-label="Allocation">
          <option value="auto">Oldest debt first</option>
          <option value="manual">Choose receipts</option>
        </select>
        <select className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={method} onChange={(e) => setMethod(e.target.value)} aria-label="Payment method">
          {["cash", "mpesa", "card", "bank"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={method2} onChange={(e) => setMethod2(e.target.value)} aria-label="Second method">
          <option value="">No second method</option>
          {["cash", "mpesa", "card", "bank"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <Input value={method2Amount} onChange={(e) => setMethod2Amount(e.target.value)} inputMode="decimal" placeholder="Second amount" aria-label="Second amount" />
      </div>
      <div className="overflow-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-panel text-left text-[10px] font-semibold uppercase tracking-wide text-text2">
            <tr>
              {["Receipt", "Date", "Original", "Paid", "Outstanding", "Allocate", "After"].map((head) => (
                <th key={head} className="px-3 py-2">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line: any) => (
              <tr key={line.invoice_id} className="border-t border-border">
                <td className="px-3 py-2 font-medium text-text">{line.invoice_number}<div className="text-xs text-text2">{line.receipt_number}</div></td>
                <td className="px-3 py-2 text-text2">{String(line.created_at || "").slice(0, 16)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(line.original, currency)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(line.paid, currency)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(line.outstanding, currency)}</td>
                <td className="px-3 py-2">
                  <Input
                    className="w-28 text-right"
                    value={manual[line.invoice_id] ?? String(line.allocate || "")}
                    disabled={mode !== "manual"}
                    onChange={(e) => setManual((current) => ({ ...current, [line.invoice_id]: e.target.value }))}
                    aria-label={`Allocate ${line.invoice_number}`}
                  />
                </td>
                <td className="px-3 py-2 tabular-nums">{KES(line.remaining, currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-gold">
        {preview
          ? `Receive ${KES(preview.amount, currency)}. Allocated ${KES(preview.allocated, currency)}. Still owed ${KES(preview.outstanding_after, currency)}. Credit ${KES(preview.unapplied, currency)}.`
          : "Enter the amount received."}
      </p>
      {error ? <p className="mt-2 text-sm text-err">{error}</p> : null}
      {note ? <p className="mt-2 text-sm text-ok">{note}</p> : null}
      <div className="mt-3">
        <Button onClick={save} disabled={busy}>Record payment</Button>
      </div>
    </div>
  );
}

function StatementPanel({
  customerId,
  currency,
  onClose,
}: {
  customerId: number;
  currency: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const statementQ = useQuery({
    queryKey: ["debt-statement", customerId],
    queryFn: () => GET<any>(`/debt/customers/${customerId}/statement`),
  });
  const data = statementQ.data || {};
  const invoices = Array.isArray(data.invoices) ? data.invoices : [];
  const collections = Array.isArray(data.collections) ? data.collections : [];

  async function reverseCollection(collectionId: number) {
    if (reason.trim().length < 3) {
      setError("Enter why this payment is being reversed.");
      return;
    }
    const res = await POST<any>(`/debt/collections/${collectionId}/reverse`, { reason });
    if (!res || res.error) {
      setError(res?.error || "The payment was not reversed.");
      return;
    }
    setError("");
    setNote(`${res.collection_receipt} reversed. The original sale was not cancelled.`);
    await qc.invalidateQueries({ queryKey: ["debt-statement", customerId] });
    await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    await qc.invalidateQueries({ queryKey: ["debt-summary"] });
    await qc.invalidateQueries({ queryKey: ["customers"] });
  }

  return (
    <div className="border-t border-border p-4">
      <div className="mb-3 flex items-center justify-between">
        <SectionTitle>Statement — {data.customer?.name || "Customer"}</SectionTitle>
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <p className="mb-3 text-sm text-text">
        Outstanding {KES(data.outstanding || 0, currency)}. Paid {KES(data.total_paid || 0, currency)}.
        Customer credit {KES(data.unapplied_credit || 0, currency)}.
      </p>
      <div className="overflow-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-panel text-left text-[10px] font-semibold uppercase tracking-wide text-text2">
            <tr>
              {["Receipt", "Date", "Original", "Paid", "Outstanding", "Status"].map((head) => (
                <th key={head} className="px-3 py-2">{head}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv: any) => (
              <tr key={inv.id} className="border-t border-border">
                <td className="px-3 py-2 font-medium">{inv.invoice_number}<div className="text-xs text-text2">{inv.receipt_number}</div></td>
                <td className="px-3 py-2 text-text2">{String(inv.created_at || "").slice(0, 16)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(inv.total_amount, currency)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(inv.amount_paid, currency)}</td>
                <td className="px-3 py-2 tabular-nums">{KES(inv.balance, currency)}</td>
                <td className="px-3 py-2">{inv.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 space-y-3">
        {collections.map((col: any) => (
          <div key={col.collection_id} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-text">
                {col.collection_receipt} · {KES(col.amount, currency)} · {(col.methods || []).map((m: any) => `${m.method} ${KES(m.amount, currency)}`).join(" + ") || col.payment_method}
                {Number(col.reversed) === 1 ? " · Reversed" : ""}
                {Number(col.unapplied) > 0 ? ` · Credit ${KES(col.unapplied, currency)}` : ""}
              </p>
              {Number(col.reversed) === 1 ? null : (
                <Button onClick={() => reverseCollection(col.collection_id)}>Reverse this payment</Button>
              )}
            </div>
            <ul className="mt-2 text-sm text-text2">
              {(col.allocations || []).map((row: any) => (
                <li key={row.id || row.payment_receipt}>
                  {row.receipt_number || row.invoice_number}: {KES(row.amount, currency)}
                  {Number(row.reversed) === 1 ? " (reversed)" : ""}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Input aria-label="Reversal reason" placeholder="Why this payment is being reversed" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-md" />
      </div>
      {error ? <p className="mt-2 text-sm text-err">{error}</p> : null}
      {note ? <p className="mt-2 text-sm text-ok">{note}</p> : null}
    </div>
  );
}

function Debt() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [payId, setPayId] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("Cash");
  const [today, setToday] = useState(localToday);
  const [payError, setPayError] = useState("");
  useEffect(() => {
    const tick = () => setToday((prev) => {
      const next = localToday();
      return prev === next ? prev : next;
    });
    const id = window.setInterval(tick, 30000);
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", tick);
    };
  }, []);
  const [payNote, setPayNote] = useState("");
  const [query, setQuery] = useState("");
  const [collectId, setCollectId] = useState<number | null>(null);
  const [statementId, setStatementId] = useState<number | null>(null);

  const summaryQ = useQuery({
    queryKey: ["debt-summary"],
    queryFn: () => GET<any>("/debt/summary"),
  });
  const invoicesQ = useQuery({
    queryKey: ["debt-invoices"],
    queryFn: () => GET<any[]>("/debt/invoices"),
    enabled: tab === "Invoices" || tab === "Overview" || tab === "Resolution" || tab === "Customers",
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
    if (today > localToday()) return setPayError("Future payment dates are not allowed.");
    if (!payToken.current) payToken.current = crypto.randomUUID();
    const res = await POST<any>(`/debt/invoices/${payId}/pay`, {
      amount,
      payment_method: payMethod,
      payment_date: today,
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
          {TABS.filter((t) => t !== "Supplier debts" || canSeeSupplierDebts()).map((t) => (
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
          label="Customer outstanding"
          value={KES(outstanding, currency)}
          sub="Money customers owe the shop"
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
                  : tab === "Payments"
                    ? "Payments"
                    : tab === "Supplier debts"
                      ? "Supplier Debts / Shop Payables"
                      : "Debt Resolution Centre"}
          </SectionTitle>
        </div>

        {tab === "Overview" || tab === "Customers" ? (
          <>
          <Table head={["Customer", "Phone", "Outstanding", "Credit", "Open", "Actions"]}>
            {(tab === "Overview" ? debtCustomers : customers).map((c: any) => (
              <tr key={c.id}>
                <td className="px-4 py-2.5 text-text font-medium">{c.name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text2">{c.phone || "—"}</td>
                <td className="px-4 py-2.5 tabular-nums text-err font-semibold">
                  {c.total_outstanding == null ? "—" : KES(c.total_outstanding || 0, currency)}
                </td>
                <td className="px-4 py-2.5 tabular-nums text-text">{KES(c.wallet_balance || 0, currency)}</td>
                <td className="px-4 py-2.5 text-text2">{c.open_invoices ?? "—"}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    {Number(c.total_outstanding) > 0 ? (
                      <Button onClick={() => { setCollectId(Number(c.id)); setStatementId(null); }}>Receive</Button>
                    ) : null}
                    <Button variant="ghost" onClick={() => { setStatementId(Number(c.id)); setCollectId(null); }}>Statement</Button>
                    {c.phone ? (
                      <a
                        href={`tel:${c.phone}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-text2 hover:text-gold hover:bg-hover"
                      >
                        <Phone className="h-3.5 w-3.5" />
                      </a>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </Table>
          {collectId ? (
            <CollectPanel
              key={collectId}
              customerId={collectId}
              customerName={(customers.find((c: any) => Number(c.id) === collectId) || debtCustomers.find((c: any) => Number(c.id) === collectId))?.name || "Customer"}
              invoices={(Array.isArray(invoicesQ.data) ? invoicesQ.data : []).filter((inv: any) => Number(inv.customer_id) === collectId && Number(inv.balance) > 0 && inv.status !== "paid" && inv.status !== "cancelled")}
              currency={currency}
              onClose={() => setCollectId(null)}
              onSaved={async () => {
                await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
                await qc.invalidateQueries({ queryKey: ["debt-summary"] });
                await qc.invalidateQueries({ queryKey: ["debt-payments"] });
                await qc.invalidateQueries({ queryKey: ["customers"] });
              }}
            />
          ) : null}
          {statementId ? (
            <StatementPanel
              customerId={statementId}
              currency={currency}
              onClose={() => setStatementId(null)}
            />
          ) : null}
          </>
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
            <Input type="date" aria-label="Payment date" value={today} readOnly />
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

        {tab === "Resolution" ? <ResolutionPanel currency={currency} invoices={invoices} /> : null}
        {tab === "Supplier debts" && canSeeSupplierDebts() ? <SupplierDebts currency={currency} /> : null}

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

function SupplierDebts({ currency }: { currency: string }) {
  const qc = useQueryClient();
  const summaryQ = useQuery({
    queryKey: ["supplier-payables"],
    queryFn: () => GET<any>("/supplier-payables"),
  });
  const [amount, setAmount] = useState("");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<any>(null);
  const data = summaryQ.data || {};
  const invoices = (Array.isArray(data.invoices) ? data.invoices : []).filter(
    (row: any) => row.payment_status !== "VOIDED",
  );
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard label="Supplier outstanding" value={KES(data.outstanding || 0, currency)} sub="Owed to suppliers" />
        <KpiCard label="Unpaid invoices" value={String(data.unpaid_count || 0)} sub="No payment yet" />
        <KpiCard label="Partially paid" value={String(data.partial_count || 0)} sub="Still a balance" />
        <KpiCard label="Overdue" value={KES(data.overdue_amount || 0, currency)} sub="Past the due date" />
      </div>
      <p className="text-sm text-text2">These bills are not customer debt and they are not sales.</p>
      <Table head={["Delivery", "Supplier", "Invoice", "Total", "Outstanding", "Status"]}>
        {invoices.map((row: any) => (
          <tr key={row.id} className="cursor-pointer" onClick={async () => {
            const full = await GET<any>(`/stock-receipts/${row.id}`);
            setOpen(full?.id ? full : row);
          }}>
            <td className="px-4 py-2.5 font-mono text-sm text-gold">{row.receipt_number}</td>
            <td className="px-4 py-2.5">{row.supplier_name}</td>
            <td className="px-4 py-2.5 text-text2">{row.reference_note || "—"}</td>
            <td className="px-4 py-2.5 tabular-nums">{KES(row.grand_total, currency)}</td>
            <td className="px-4 py-2.5 tabular-nums font-semibold">{KES(row.outstanding, currency)}</td>
            <td className="px-4 py-2.5">{row.payment_status}</td>
          </tr>
        ))}
      </Table>
      {canPaySupplier() ? (
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs font-semibold text-text2">
          Pay the selected supplier, oldest invoice first
          <Input aria-label="Supplier payment" type="number" min={0} step={0.01} value={amount} onChange={(e) => setAmount(e.target.value)} className="mt-1 h-11 w-48" />
        </label>
        <Button onClick={async () => {
          if (!open?.supplier_id) {
            setMsg("Open an invoice first, then enter the amount.");
            return;
          }
          const saved = await POST<any>("/supplier-payments", {
            supplier_id: open.supplier_id,
            amount: Number(amount),
            method: "cash",
            mode: "oldest",
          });
          setMsg(saved?.success ? `${saved.payment_number} recorded.` : (saved?.error || "Could not record the payment."));
          if (saved?.success) {
            setAmount("");
            qc.invalidateQueries({ queryKey: ["supplier-payables"] });
            const full = await GET<any>(`/stock-receipts/${open.id}`);
            if (full?.id) setOpen(full);
          }
        }}>Record payment</Button>
      </div>
      ) : null}
      {msg ? <p className="text-sm text-text2">{msg}</p> : null}
      {open?.receipt_number ? (
        <div className="rounded-xl border border-border p-4 text-sm">
          <div className="font-extrabold text-text">{open.receipt_number} · {open.supplier_name}</div>
          <div className="mt-1 text-text2">
            Invoice {Number(open.grand_total || 0).toFixed(2)} · Paid {Number(open.amount_paid || 0).toFixed(2)} · Outstanding {Number(open.outstanding || 0).toFixed(2)} · {open.payment_status}
          </div>
          {(open.lines || []).map((line: any, index: number) => (
            <div key={`${line.product_name}-${index}`} className="mt-1">
              {index + 1}. {line.product_name} · {line.quantity} × {Number(line.unit_cost || 0).toFixed(2)}
              {line.returned_qty ? ` · returned ${line.returned_qty}` : ""}
            </div>
          ))}
          <DeliveryActions
            receipt={open}
            onChanged={(next) => {
              setOpen(next);
              qc.invalidateQueries({ queryKey: ["supplier-payables"] });
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

function ResolutionPanel({ currency, invoices }: { currency: string; invoices: any[] }) {
  const qc = useQueryClient();
  const [invoiceId, setInvoiceId] = useState("");
  const [operation, setOperation] = useState<"reverse" | "cancel" | "writeoff">("reverse");
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState("never_received");
  const [refundStatus, setRefundStatus] = useState("none");
  const [refundMethod, setRefundMethod] = useState("Cash");
  const [refundReference, setRefundReference] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [writeAmount, setWriteAmount] = useState("");
  const [pin, setPin] = useState("");
  const [restoreQty, setRestoreQty] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<any>(null);
  const [confirming, setConfirming] = useState("");
  const previewQ = useQuery({
    queryKey: ["debt-resolution", invoiceId],
    queryFn: () => GET<any>(`/debts/${invoiceId}/resolution`),
    enabled: Boolean(invoiceId),
  });
  const preview = previewQ.data || {};
  const payments = Array.isArray(preview.payments) ? preview.payments : [];
  const lines = Array.isArray(preview.lines) ? preview.lines : [];
  const outstanding = Number(preview.outstanding ?? preview.invoice?.balance ?? 0);
  const moneyReceived = Number(preview.money_received ?? preview.valid_repayments ?? 0);

  async function reverse(payment: any) {
    setError("");
    setMessage("");
    if (reason.trim().length < 3) {
      setError("Enter why this payment is being reversed.");
      return;
    }
    setPending(payment);
  }

  async function confirmReverse() {
    const payment = pending;
    if (!payment) return;
    setBusy(true);
    try {
      const res = await POST<any>(`/debt-payments/${payment.id}/reverse`, {
        reason: reason.trim(),
        money_outcome: outcome,
        client_token: crypto.randomUUID(),
      });
      if (!res || res.error) {
        setError(res?.error || "The reversal was not saved.");
        return;
      }
      setMessage(`Payment reversed. Outstanding is now ${KES(res.balance, currency)}. The sale was not cancelled.`);
      setReason("");
      await qc.invalidateQueries({ queryKey: ["debt-resolution", invoiceId] });
      await qc.invalidateQueries({ queryKey: ["debt-summary"] });
      await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  function askCancel() {
    setError("");
    setMessage("");
    if (reason.trim().length < 3) {
      setError("Enter why this sale is being cancelled.");
      return;
    }
    if (moneyReceived > 0.009 && refundStatus === "none") {
      setError("Money was received. Choose a completed refund or leave the refund pending.");
      return;
    }
    setConfirming("cancel");
  }

  async function confirmCancel() {
    setBusy(true);
    try {
      const restore = lines.filter((line: any) => line.product_id).map((line: any) => ({
        product_id: line.product_id,
        quantity: Number(restoreQty[String(line.product_id)] ?? line.eligible ?? 0),
      }));
      const res = await POST<any>(`/debts/${invoiceId}/cancel-sale`, {
        reason: reason.trim(),
        refund_status: moneyReceived > 0.009 ? refundStatus : "none",
        refund_method: refundMethod,
        refund_reference: refundReference,
        refund_amount: refundAmount === "" ? undefined : Number(refundAmount),
        restore,
        client_token: crypto.randomUUID(),
      });
      if (!res || res.error) {
        setError(res?.error || "The sale was not cancelled.");
        return;
      }
      setMessage("Sale cancelled. The debt is cleared. Stock changed only for the quantities you confirmed.");
      setReason("");
      await qc.invalidateQueries({ queryKey: ["debt-resolution", invoiceId] });
      await qc.invalidateQueries({ queryKey: ["debt-summary"] });
      await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    } finally {
      setBusy(false);
      setConfirming("");
    }
  }

  function askWriteOff() {
    setError("");
    setMessage("");
    const amount = Number(writeAmount);
    if (!(amount > 0) || amount - outstanding > 0.001) {
      setError("Enter an amount up to the outstanding balance.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Enter why this debt is being written off.");
      return;
    }
    setConfirming("writeoff");
  }

  async function confirmWriteOff() {
    setBusy(true);
    try {
      const res = await POST<any>(`/debts/${invoiceId}/write-off`, {
        amount: Number(writeAmount),
        reason: reason.trim(),
        pin,
        client_token: crypto.randomUUID(),
      });
      if (!res || res.error) {
        setError(res?.error || "The write-off was not saved.");
        return;
      }
      setMessage(`Write-off saved. Outstanding is now ${KES(res.balance, currency)}. This was not a repayment and the sale was not cancelled.`);
      setPin("");
      setWriteAmount("");
      setReason("");
      await qc.invalidateQueries({ queryKey: ["debt-resolution", invoiceId] });
      await qc.invalidateQueries({ queryKey: ["debt-summary"] });
      await qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    } finally {
      setBusy(false);
      setConfirming("");
    }
  }

  const ops = [
    ["reverse", "Reverse Payment / Restore Debt", "Correct one repayment. The original sale stays."],
    ["cancel", "Cancel Sale & Reverse Debt", "Cancel the original sale and resolve its debt, money, and stock."],
    ["writeoff", "Debt Adjustment / Write-Off", "Reduce the balance. The sale stays and no stock comes back."],
  ] as const;

  return (
    <div className="p-4 space-y-3">
      <div className="grid gap-2 md:grid-cols-3">
        {ops.map(([key, title, copy]) => (
          <button
            key={key}
            type="button"
            onClick={() => { setOperation(key); setConfirming(""); setPending(null); setError(""); }}
            className={`rounded-lg border p-3 text-left ${operation === key ? "border-gold bg-gold/10" : "border-border"}`}
          >
            <div className="text-sm font-extrabold text-text">{title}</div>
            <div className="mt-1 text-xs text-text2">{copy}</div>
          </button>
        ))}
      </div>
      <select
        aria-label="Debt to resolve"
        className="h-9 w-full max-w-xl rounded-lg border border-border bg-input px-3 text-sm"
        value={invoiceId}
        onChange={(e) => { setInvoiceId(e.target.value); setMessage(""); setError(""); setConfirming(""); }}
      >
        <option value="">Choose a debt</option>
        {invoices.map((inv) => (
          <option key={inv.id} value={inv.id}>
            {inv.invoice_number} · {inv.customer_name} · {inv.receipt_number || "no receipt"} · owed {KES(inv.balance, currency)}
          </option>
        ))}
      </select>
      {invoiceId && previewQ.isLoading ? <p className="text-sm text-text2">Loading this debt…</p> : null}
      {invoiceId && preview.invoice ? (
        <div className="rounded-lg border border-border p-3 text-sm space-y-1">
          <div className="font-extrabold text-text">Debt {preview.invoice.invoice_number}</div>
          <div>Customer {preview.invoice.customer_name}</div>
          <div>Original credit {KES(preview.invoice.total_amount, currency)}</div>
          <div>Money received {KES(moneyReceived, currency)}</div>
          <div className="font-extrabold text-err">Outstanding {KES(outstanding, currency)}</div>
          <div>{preview.sale ? `Sale ${preview.sale.receipt_number} is ${preview.sale.status}.` : "No linked sale."}</div>
          <div>
            {operation === "reverse" ? "A payment reversal does not restore stock and does not cancel the sale." : null}
            {operation === "cancel" ? "Cancelling the sale removes the debt. Stock returns only for quantities you confirm." : null}
            {operation === "writeoff" ? "A write-off is not a repayment and does not cancel the sale." : null}
          </div>
        </div>
      ) : null}
      {operation === "reverse" ? (
        <>
          <div className="flex flex-wrap gap-2">
            <Input aria-label="Reversal reason" placeholder="Why this payment is being reversed" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-md" />
            <select aria-label="What happened to the money" className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="never_received">Money was never received</option>
              <option value="refunded">Money was received and has been refunded</option>
            </select>
          </div>
          {payments.length ? (
            <Table head={["Repayment", "Amount", "Method", "Status", ""]}>
              {payments.map((payment: any) => (
                <tr key={payment.id}>
                  <td className="px-4 py-2 font-mono text-xs">{payment.payment_receipt}</td>
                  <td className="px-4 py-2 tabular-nums">{KES(payment.amount, currency)}</td>
                  <td className="px-4 py-2">{payment.payment_method}</td>
                  <td className="px-4 py-2">{Number(payment.reversed) === 1 ? "Reversed" : "Valid"}</td>
                  <td className="px-4 py-2">
                    {Number(payment.reversed) === 1 ? null : (
                      <Button disabled={busy} onClick={() => reverse(payment)}>Reverse payment</Button>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          ) : invoiceId && !previewQ.isLoading ? <p className="text-sm text-text2">This debt has no repayments to reverse.</p> : null}
        </>
      ) : null}
      {operation === "cancel" && invoiceId && preview.invoice ? (
        <div className="space-y-2">
          <Input aria-label="Cancellation reason" placeholder="Why this sale is being cancelled" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-md" />
          <select aria-label="Refund" className="h-9 rounded-lg border border-border bg-input px-3 text-sm" value={moneyReceived > 0.009 ? refundStatus : "none"} onChange={(e) => setRefundStatus(e.target.value)} disabled={moneyReceived <= 0.009}>
            <option value="none">No refund due</option>
            <option value="pending">Refund pending</option>
            <option value="completed">Refund completed</option>
          </select>
          {refundStatus === "completed" && moneyReceived > 0.009 ? (
            <div className="flex flex-wrap gap-2">
              <Input aria-label="Refund amount" placeholder="Amount refunded" value={refundAmount} onChange={(e) => setRefundAmount(e.target.value)} className="max-w-[160px]" />
              <Input aria-label="Refund method" placeholder="Cash, M-Pesa, or bank" value={refundMethod} onChange={(e) => setRefundMethod(e.target.value)} className="max-w-[180px]" />
              <Input aria-label="Refund reference" placeholder="Reference" value={refundReference} onChange={(e) => setRefundReference(e.target.value)} className="max-w-[180px]" />
            </div>
          ) : null}
          {lines.map((line: any) => (
            <label key={line.product_id || line.product_name} className="flex items-center gap-3 text-sm">
              <span className="min-w-40">{line.product_name}</span>
              <span className="text-text2">Sold {line.sold}. Eligible {line.eligible}.</span>
              <Input aria-label={`Restore ${line.product_name}`} className="max-w-[90px]" value={restoreQty[String(line.product_id)] ?? String(line.eligible ?? 0)} onChange={(e) => setRestoreQty((prev) => ({ ...prev, [String(line.product_id)]: e.target.value }))} />
            </label>
          ))}
          <Button disabled={busy || preview.sale?.status === "voided"} onClick={askCancel}>Cancel sale & reverse debt</Button>
        </div>
      ) : null}
      {operation === "writeoff" && invoiceId && preview.invoice ? (
        <div className="flex flex-wrap gap-2">
          <Input aria-label="Write-off amount" placeholder="Amount to write off" value={writeAmount} onChange={(e) => setWriteAmount(e.target.value)} className="max-w-[180px]" />
          <Input aria-label="Write-off reason" placeholder="Why this balance is being reduced" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-md" />
          <Input aria-label="Super Admin PIN" type="password" placeholder="Super Admin PIN" value={pin} onChange={(e) => setPin(e.target.value)} className="max-w-[180px]" />
          <Button disabled={busy || outstanding <= 0} onClick={askWriteOff}>Write off</Button>
        </div>
      ) : null}
      {pending ? (
        <div className="rounded-lg border border-gold/50 bg-gold/10 p-3 text-sm space-y-2">
          <div className="font-extrabold">Confirm reversal</div>
          <div>Current debt {KES(outstanding, currency)}. Reversal {KES(pending.amount, currency)}. New debt {KES(outstanding + Number(pending.amount), currency)}.</div>
          <div>The original sale stays valid. Stock is not restored. {outcome === "refunded" ? "A refund is recorded because the money was returned." : "No refund is recorded, because the money was never received."}</div>
          <Button disabled={busy} onClick={confirmReverse}>{busy ? "Reversing…" : "Confirm reversal"}</Button>
        </div>
      ) : null}
      {confirming === "cancel" ? (
        <div className="rounded-lg border border-err/40 bg-err/10 p-3 text-sm space-y-2">
          <div className="font-extrabold">Confirm sale cancellation</div>
          <div>Outstanding {KES(outstanding, currency)} will be cleared. Money received {KES(moneyReceived, currency)}. Refund: {moneyReceived > 0.009 ? refundStatus : "none"}.</div>
          <div>The original receipt stays on file. Stock returns only for the quantities shown above.</div>
          <Button disabled={busy} onClick={confirmCancel}>{busy ? "Cancelling…" : "Confirm cancellation"}</Button>
        </div>
      ) : null}
      {confirming === "writeoff" ? (
        <div className="rounded-lg border border-gold/50 bg-gold/10 p-3 text-sm space-y-2">
          <div className="font-extrabold">Confirm write-off</div>
          <div>Current debt {KES(outstanding, currency)}. Write-off {KES(Number(writeAmount), currency)}. New debt {KES(Math.max(0, outstanding - Number(writeAmount)), currency)}.</div>
          <div>The sale stays valid. No repayment is recorded. Stock is not restored.</div>
          <Button disabled={busy} onClick={confirmWriteOff}>{busy ? "Saving…" : "Confirm write-off"}</Button>
        </div>
      ) : null}
      {error ? <p className="text-sm text-err">{error}</p> : null}
      {message ? <p className="text-sm text-ok">{message}</p> : null}
    </div>
  );
}
