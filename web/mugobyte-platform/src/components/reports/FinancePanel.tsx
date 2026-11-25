import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { GET } from "@/lib/api";
import { formatMoney } from "./analytics";
import { ReportState, responseError } from "./ReportState";

type Finance = {
  currency?: string;
  sales_revenue?: number;
  refunds?: number;
  net_sales?: number;
  cost_of_goods?: number;
  gross_profit?: number;
  uncosted_lines?: number;
  uncosted_sales?: number;
  expenses?: number | null;
  expenses_outside?: number;
  supplier_purchases?: number | null;
  purchases_outside?: number;
  supplier_payments?: number | null;
  supplier_payments_outside?: number;
  customer_credit_sales?: number;
  debt_repayments?: number;
  outstanding_customer_debts?: number;
  cash_collected?: number;
  note?: string;
  error?: string;
};

function show(amount: number | null | undefined, currency: string, blank = "Not uploaded") {
  if (amount === null || amount === undefined) return blank;
  return formatMoney(amount, currency);
}

function period(amount: number | null | undefined, outside: number | undefined, currency: string) {
  if (amount === 0 && outside) return "None in this date range";
  return show(amount, currency);
}

export function FinancePanel({ orgId, start, end }: { orgId: string; start: string; end: string }) {
  const query = useQuery({
    queryKey: ["cloud-finance", orgId, start, end],
    queryFn: () => GET<Finance>("/cloud/analytics/finance", { org_id: orgId, start, end }),
    enabled: Boolean(orgId),
  });
  const data = query.data || {};
  const currency = data.currency || "KES";
  const rows: Array<[string, string]> = [
    ["Sales revenue", show(data.sales_revenue, currency)],
    ["Returns and refunds", show(data.refunds, currency)],
    ["Net sales", show(data.net_sales, currency)],
    ["Cost of goods from batch snapshots", show(data.cost_of_goods, currency, "Unknown")],
    ["Gross profit", show(data.gross_profit, currency, "Unknown")],
    ["Sales with no batch cost", show(data.uncosted_sales, currency)],
    ["Cash collected on sales", show(data.cash_collected, currency)],
    ["Customer credit sales", show(data.customer_credit_sales, currency)],
    ["Customer debt repayments", show(data.debt_repayments, currency)],
    ["Outstanding customer debts now", show(data.outstanding_customer_debts, currency)],
    ["Expenses in this date range", period(data.expenses, data.expenses_outside, currency)],
    ["Supplier purchases in this date range", period(data.supplier_purchases, data.purchases_outside, currency)],
    ["Supplier payments in this date range", period(data.supplier_payments, data.supplier_payments_outside, currency)],
  ];
  return (
    <ReportState
      loading={query.isLoading}
      error={responseError(query.data, query.error)}
      empty={false}
      onRetry={() => void query.refetch()}
    >
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">{data.note}</p>
        {data.purchases_outside ? (
          <p className="text-sm text-muted-foreground">
            {data.purchases_outside} uploaded purchase{data.purchases_outside === 1 ? "" : "s"} sit outside this date range. They stay on the supplier register and are not treated as zero.
          </p>
        ) : null}
        <Card>
          <CardContent className="grid gap-3 p-4 sm:grid-cols-2">
            {rows.map(([label, amount]) => (
              <div key={label} className="rounded-lg border px-3 py-2">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-1 text-lg font-semibold">{amount}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </ReportState>
  );
}
