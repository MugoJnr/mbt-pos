import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Phone, Banknote, Users, AlertTriangle, TrendingDown } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, KpiCard, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { GET, POST, getUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/debt")({
  component: Debt,
});

const TABS = ["Overview", "Invoices", "Customers", "Payments"] as const;

function Debt() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || getUser()?.role || "").toLowerCase();
  const isSuperAdmin = role === "superadmin";
  const canCollect = ["cashier", "manager", "admin", "superadmin"].includes(role);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [payInv, setPayInv] = useState<any | null>(null);
  const [woInv, setWoInv] = useState<any | null>(null);

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

  const invoices = Array.isArray(invoicesQ.data) ? invoicesQ.data : [];
  const customers = Array.isArray(customersQ.data) ? customersQ.data : [];
  const payments = Array.isArray(paymentsQ.data) ? paymentsQ.data : [];

  const debtCustomers = customers
    .filter((c) => Number(c.total_outstanding || 0) > 0)
    .sort((a, b) => Number(b.total_outstanding) - Number(a.total_outstanding));

  function refreshDebt() {
    qc.invalidateQueries({ queryKey: ["debt-summary"] });
    qc.invalidateQueries({ queryKey: ["debt-invoices"] });
    qc.invalidateQueries({ queryKey: ["debt-payments"] });
    qc.invalidateQueries({ queryKey: ["customers"] });
  }

  return (
    <AppShell title="Debt Management">
      <PageHeader
        eyebrow="Operations"
        title="Debt Management"
        description="Outstanding credit, collections, and Super Admin write-off."
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
                  {KES(c.total_outstanding || 0, currency)}
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
          <Table head={["Invoice", "Customer", "Total", "Balance", "Status", "Due", "Actions"]}>
            {invoices.map((inv: any) => {
              const open = inv.status !== "paid" && inv.status !== "cancelled";
              return (
                <tr key={inv.id}>
                  <td className="px-4 py-2.5 font-mono text-sm text-text">{inv.invoice_number}</td>
                  <td className="px-4 py-2.5 text-text">{inv.customer_name}</td>
                  <td className="px-4 py-2.5 tabular-nums">{KES(inv.total_amount, currency)}</td>
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
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {open && canCollect ? (
                        <Button size="sm" variant="secondary" onClick={() => setPayInv(inv)}>
                          Collect
                        </Button>
                      ) : null}
                      {open && isSuperAdmin ? (
                        <Button size="sm" variant="ghost" onClick={() => setWoInv(inv)}>
                          Write off
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </Table>
        ) : null}

        {tab === "Payments" ? (
          <Table head={["Receipt", "Customer", "Invoice", "Amount", "Method", "When"]}>
            {payments.map((p: any) => (
              <tr key={p.id}>
                <td className="px-4 py-2.5 font-mono text-sm">{p.payment_receipt}</td>
                <td className="px-4 py-2.5 text-text">{p.customer_name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.invoice_number}</td>
                <td className="px-4 py-2.5 tabular-nums text-ok font-semibold">
                  {KES(p.amount, currency)}
                </td>
                <td className="px-4 py-2.5 text-text2">{p.payment_method}</td>
                <td className="px-4 py-2.5 text-text2 text-xs">
                  {(p.created_at || "").slice(0, 16)}
                </td>
              </tr>
            ))}
          </Table>
        ) : null}

        {!summaryQ.isLoading &&
        ((tab === "Overview" && !debtCustomers.length) ||
          (tab === "Invoices" && !invoices.length) ||
          (tab === "Customers" && !customers.length) ||
          (tab === "Payments" && !payments.length)) ? (
          <div className="py-12 text-center text-sm text-text2">No records in this view.</div>
        ) : null}
      </Card>

      {payInv ? (
        <CollectModal
          inv={payInv}
          currency={currency}
          onClose={() => setPayInv(null)}
          onDone={() => {
            setPayInv(null);
            refreshDebt();
          }}
        />
      ) : null}
      {woInv ? (
        <WriteOffModal
          inv={woInv}
          currency={currency}
          onClose={() => setWoInv(null)}
          onDone={() => {
            setWoInv(null);
            refreshDebt();
          }}
        />
      ) : null}
    </AppShell>
  );
}

function CollectModal({
  inv,
  currency,
  onClose,
  onDone,
}: {
  inv: any;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(String(inv.balance || ""));
  const [method, setMethod] = useState("cash");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    const res = await POST<any>(`/debt/invoices/${inv.id}/pay`, {
      amount: Number(amount),
      payment_method: method,
      notes,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(res.message || "Payment recorded");
      onDone();
    } else {
      toast.error(res?.error || "Collect failed");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-text mb-1">Collect payment</h3>
        <p className="text-sm text-text2 mb-4">
          {inv.invoice_number} · {inv.customer_name} · balance {KES(inv.balance, currency)}
        </p>
        <div className="space-y-3">
          <label className="block text-xs font-medium text-text2">
            Amount
            <Input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" min="0.01" step="0.01" />
          </label>
          <label className="block text-xs font-medium text-text2">
            Method
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-sm text-text"
              value={method}
              onChange={(e) => setMethod(e.target.value)}
            >
              <option value="cash">Cash</option>
              <option value="mpesa">M-Pesa</option>
              <option value="bank">Bank</option>
              <option value="card">Card</option>
            </select>
          </label>
          <label className="block text-xs font-medium text-text2">
            Notes
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            Record payment
          </Button>
        </div>
      </div>
    </div>
  );
}

function WriteOffModal({
  inv,
  currency,
  onClose,
  onDone,
}: {
  inv: any;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!reason.trim()) {
      toast.error("Reason required");
      return;
    }
    setBusy(true);
    const res = await POST<any>(`/debt/invoices/${inv.id}/write-off`, {
      reason: reason.trim(),
      pin,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(res.message || "Debt written off");
      onDone();
    } else {
      toast.error(res?.error || "Write-off failed");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-text mb-1">Write off debt</h3>
        <p className="text-sm text-text2 mb-4">
          Super Admin only. {inv.invoice_number} · remaining {KES(inv.balance, currency)}.
          Unpaid invoices may void the linked sale and restock.
        </p>
        <div className="space-y-3">
          <label className="block text-xs font-medium text-text2">
            Reason
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={240} />
          </label>
          <label className="block text-xs font-medium text-text2">
            Super-Admin PIN
            <Input value={pin} onChange={(e) => setPin(e.target.value)} type="password" autoComplete="off" />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            Write off
          </Button>
        </div>
      </div>
    </div>
  );
}
