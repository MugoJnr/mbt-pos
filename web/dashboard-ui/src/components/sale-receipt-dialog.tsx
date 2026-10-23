import { useQuery } from "@tanstack/react-query";
import { Button, Card } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

type SaleLine = {
  product_name?: string;
  sku?: string;
  product_sku?: string;
  barcode?: string;
  category?: string;
  unit?: string;
  quantity?: number;
  unit_price?: number;
  discount?: number;
  total?: number;
  product_price?: number;
  cost_price?: number;
  current_stock?: number;
};

type SaleDetail = {
  receipt_number?: string;
  status?: string;
  sale_date?: string;
  created_at?: string;
  cashier_name?: string;
  payment_method?: string;
  customer_name?: string;
  customer_phone?: string;
  subtotal?: number;
  discount?: number;
  tax?: number;
  total?: number;
  amount_paid?: number;
  notes?: string;
  items?: SaleLine[];
  debt?: {
    invoice_number?: string;
    status?: string;
    balance?: number;
  };
  error?: string;
};

function money(value: unknown, currency: string) {
  return KES(Number(value || 0), currency);
}

function field(label: string, value: string) {
  return (
    <div key={label}>
      <div className="text-xs text-text2">{label}</div>
      <div className="mt-1 font-semibold text-text">{value}</div>
    </div>
  );
}

export function SaleReceiptDialog({
  saleId,
  currency = "KES",
  onClose,
}: {
  saleId: number | null;
  currency?: string;
  onClose: () => void;
}) {
  const detailQ = useQuery({
    queryKey: ["sale-detail", saleId],
    enabled: saleId != null,
    queryFn: () => GET<SaleDetail>(`/sales/${saleId}`),
  });

  if (saleId == null) return null;
  const sale = detailQ.data || {};
  const items = Array.isArray(sale.items) ? sale.items : [];
  const status = String(sale.status || "completed");
  const voided = status.toLowerCase() === "void" || status.toLowerCase() === "voided";
  const saleDay = String(sale.sale_date || sale.created_at || "").slice(0, 10);
  const recorded = String(sale.created_at || "").replace("T", " ").slice(0, 19);
  const customer = sale.customer_name
    ? `${sale.customer_name}${sale.customer_phone ? ` · ${sale.customer_phone}` : ""}`
    : "Walk-in";

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div className="max-h-[90dvh] w-full max-w-3xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <Card className="overflow-hidden">
          <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-text2">Receipt</div>
              <div className="mt-1 text-lg font-extrabold text-text">
                {sale.receipt_number || `Sale ${saleId}`}
              </div>
              <div className={voided ? "text-sm font-semibold text-err" : "text-sm text-text2"}>
                {status.toUpperCase()} · {saleDay || "—"} · {sale.cashier_name || "—"}
              </div>
            </div>
            <Button variant="ghost" onClick={onClose}>
              Close
            </Button>
          </div>
          {detailQ.isLoading ? (
            <div className="px-5 py-8 text-sm text-text2">Loading receipt…</div>
          ) : detailQ.isError || sale.error ? (
            <div className="px-5 py-8 text-sm text-err">Could not load that receipt.</div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 px-5 py-4 text-sm sm:grid-cols-3">
                {field("Recorded", recorded || "—")}
                {field("Payment", String(sale.payment_method || "—"))}
                {field("Customer", customer)}
                {field("Subtotal", money(sale.subtotal, currency))}
                {field("Discount", money(sale.discount, currency))}
                {field("Tax", money(sale.tax, currency))}
                {field("Total", money(sale.total, currency))}
                {field("Paid", money(sale.amount_paid, currency))}
              </div>
              {sale.notes ? (
                <div className="border-t border-border px-5 py-3 text-sm">
                  <div className="text-xs text-text2">Notes</div>
                  <div className="mt-1 text-text">{sale.notes}</div>
                </div>
              ) : null}
              <div className="border-t border-border px-5 pt-4 text-xs font-semibold uppercase tracking-wide text-text2">
                Products
              </div>
              {items.length === 0 ? (
                <div className="px-5 py-4 text-sm text-text2">No line items on this receipt.</div>
              ) : (
                <div className="divide-y divide-border">
                  {items.map((item, index) => {
                    const name = item.product_name || "—";
                    const sku = item.sku || item.product_sku || "—";
                    return (
                      <div key={`${name}-${index}`} className="px-5 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="font-semibold text-text">{name}</div>
                            <div className="text-xs text-text2">
                              {item.category || "General"} · {sku} · {item.barcode || "—"} ·{" "}
                              {item.unit || "pcs"}
                            </div>
                          </div>
                          <div className="font-semibold tabular-nums text-gold">
                            {money(item.total, currency)}
                          </div>
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                          {field("Qty", `${Number(item.quantity || 0)}`)}
                          {field("Unit price", money(item.unit_price, currency))}
                          {field("Discount", money(item.discount, currency))}
                          {field("Line total", money(item.total, currency))}
                          {field(
                            "Selling price",
                            item.product_price == null ? "—" : money(item.product_price, currency),
                          )}
                          {field(
                            "Cost",
                            item.cost_price == null ? "—" : money(item.cost_price, currency),
                          )}
                          {field(
                            "On hand now",
                            item.current_stock == null ? "—" : String(Number(item.current_stock)),
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {sale.debt ? (
                <div className="border-t border-border px-5 py-4 text-sm text-text2">
                  Linked debt: {sale.debt.invoice_number || "—"} · {sale.debt.status || "—"} · balance{" "}
                  {money(sale.debt.balance, currency)}
                </div>
              ) : null}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
