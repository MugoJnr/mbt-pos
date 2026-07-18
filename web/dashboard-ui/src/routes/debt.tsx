import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Phone, Receipt, Banknote, Users, AlertTriangle, TrendingDown } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, KpiCard, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/debt")({
  component: Debt,
});

const TABS = ["Overview", "Invoices", "Customers", "Payments"] as const;

function Debt() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");

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

  return (
    <AppShell title="Debt Management">
      <PageHeader
        eyebrow="Operations"
        title="Debt Management"
        description="Outstanding credit, overdue accounts, and collections."
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
          <Table head={["Invoice", "Customer", "Total", "Balance", "Status", "Due"]}>
            {invoices.map((inv: any) => (
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
              </tr>
            ))}
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
