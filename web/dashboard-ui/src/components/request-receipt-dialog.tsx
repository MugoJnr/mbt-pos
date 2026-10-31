import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { PaymentBreakdown, type SalePayments } from "@/components/payment-breakdown";
import { Button, Card } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

export type ReceiptLine = {
  product_name?: string;
  sku?: string;
  unit?: string;
  quantity?: number;
  unit_price?: number;
  total?: number;
  total_cost?: number;
};

export type LinkedReceipt = {
  id?: number;
  receipt_number?: string;
  status?: string;
  total?: number;
  subtotal?: number;
  discount?: number;
  tax?: number;
  amount_paid?: number;
  change_amount?: number;
  payment_method?: string;
  cashier_name?: string;
  customer_name?: string;
  customer_phone?: string;
  sale_date?: string;
  created_at?: string;
  notes?: string;
};

function when(value?: string) {
  return String(value || "").replace("T", " ").slice(0, 19) || "—";
}

function money(value: unknown) {
  return KES(Number(value || 0));
}

export function RequestReceiptDialog({
  title,
  status,
  reason,
  requester,
  submittedAt,
  receipt,
  lines,
  note,
  consumption,
  consumptionId,
  onClose,
  children,
}: {
  title: string;
  status?: string;
  reason?: string;
  requester?: string;
  submittedAt?: string;
  receipt?: LinkedReceipt | null;
  lines?: ReceiptLine[];
  note?: string;
  consumption?: {
    reference_no?: string;
    reason?: string;
    notes?: string;
    taken_by?: string;
    department_name?: string;
    created_by_name?: string;
    created_at?: string;
    date?: string;
    voided?: number;
    total_cost?: number;
    items?: ReceiptLine[];
  } | null;
  consumptionId?: number | null;
  onClose: () => void;
  children?: ReactNode;
}) {
  const saleId = consumption || consumptionId ? 0 : Number(receipt?.id || 0);
  const saleQ = useQuery({
    queryKey: ["sale-detail", saleId],
    enabled: saleId > 0,
    queryFn: () => GET<any>(`/sales/${saleId}`),
  });
  const loadedQ = useQuery({
    queryKey: ["consumption-detail", consumptionId],
    enabled: !consumption && Number(consumptionId || 0) > 0,
    queryFn: () => GET<any>(`/consumptions/${consumptionId}`),
  });
  const loaded = loadedQ.data && !loadedQ.data.error ? loadedQ.data : null;
  const shownConsumption = consumption || (loaded ? {
    reference_no: loaded.reference_no,
    reason: loaded.reason,
    notes: loaded.notes,
    taken_by: loaded.taken_by,
    department_name: loaded.department_name,
    created_by_name: loaded.created_by_name,
    created_at: loaded.created_at,
    date: loaded.date,
    voided: loaded.voided,
    total_cost: loaded.total_cost,
    items: loaded.items,
  } : null);
  const consumptionLines = shownConsumption ? (shownConsumption.items || lines || []) : [];
  if (consumptionId && !shownConsumption) {
    return (
      <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
        <div className="w-full max-w-lg" onClick={(event) => event.stopPropagation()}>
        <Card className="p-5">
          <div className="text-sm text-text2">{loadedQ.data?.error || "Loading the consumption receipt…"}</div>
          <Button className="mt-3" variant="ghost" onClick={onClose}>Close</Button>
        </Card>
        </div>
      </div>
    );
  }
  if (shownConsumption) {
    const voided = Number(shownConsumption.voided || 0) === 1;
    return (
      <div className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-0 sm:place-items-center sm:p-4" onClick={onClose}>
        <div className="max-h-[94dvh] w-full max-w-2xl overflow-y-auto" onClick={(event) => event.stopPropagation()}>
          <Card className="overflow-hidden rounded-b-none sm:rounded-b-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-gold">Internal consumption</div>
                <div className="mt-1 text-lg font-extrabold text-text">{shownConsumption.reference_no || title}</div>
                <div className="text-sm text-text2">
                  {voided ? "Voided" : "Recorded"} · {when(shownConsumption.created_at || shownConsumption.date)} · business date {String(shownConsumption.date || "").slice(0, 10) || "—"}
                </div>
                <div className="text-sm text-text2">
                  {shownConsumption.created_by_name || "—"} · {shownConsumption.department_name || "No department"} · {shownConsumption.taken_by || "No person named"}
                </div>
              </div>
              <Button variant="ghost" onClick={onClose}>Close</Button>
            </div>
            <div className="space-y-4 px-5 py-4 text-sm">
              <p className="text-text2">This is stock used by the business. It is not a customer sale and has no payment.</p>
              <div>Reason <span className="font-semibold text-text">{shownConsumption.reason || "—"}</span></div>
              {shownConsumption.notes ? <div>Notes {shownConsumption.notes}</div> : null}
              <div className="rounded-lg border border-border">
                {consumptionLines.length === 0 ? <div className="px-3 py-3 text-text2">No product lines are stored on this consumption.</div> : consumptionLines.map((line, index) => (
                  <div key={index} className="grid grid-cols-[1fr_auto_auto] gap-2 border-b border-border px-3 py-2 last:border-0">
                    <div>
                      <div className="font-semibold text-text">{line.product_name || "Product"}</div>
                      <div className="text-xs text-text2">{line.sku || "No SKU"}</div>
                    </div>
                    <div className="text-right tabular-nums">{line.quantity}</div>
                    <div className="text-right font-semibold tabular-nums text-gold">{money(line.total_cost)}</div>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border bg-panel px-4 py-3">
                <span className="text-sm text-text2">Stock cost</span>
                <span className="text-xl font-extrabold tabular-nums text-gold">{money(shownConsumption.total_cost)}</span>
              </div>
              <div className="rounded-lg border border-border bg-panel px-3 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-text2">Request {status || "—"}</div>
                <div className="mt-1">Requested by {requester || "—"} · {when(submittedAt)}</div>
                <div className="mt-1">Reason: {reason || "—"}</div>
                {note ? <div className="mt-1 text-text2">{note}</div> : null}
              </div>
              {children ? <div className="border-t border-border pt-4">{children}</div> : null}
            </div>
          </Card>
        </div>
      </div>
    );
  }
  const missing = saleQ.data?.error;
  const sale = saleQ.data && !missing ? saleQ.data : null;
  const shown = sale || receipt || {};
  const itemRows: ReceiptLine[] = Array.isArray(sale?.items) && sale.items.length ? sale.items : (lines || []);
  const receiptNo = shown.receipt_number || title;
  const saleStatus = String(shown.status || "—");
  const payments = (sale?.payments || (receipt as { payments?: SalePayments } | null)?.payments) as SalePayments | undefined;
  const customer = shown.customer_name
    ? `${shown.customer_name}${shown.customer_phone ? ` · ${shown.customer_phone}` : ""}`
    : "Walk-in";

  return (
    <div className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-0 sm:place-items-center sm:p-4" onClick={onClose}>
      <div className="max-h-[94dvh] w-full max-w-2xl overflow-y-auto" onClick={(event) => event.stopPropagation()}>
        <Card className="overflow-hidden rounded-b-none sm:rounded-b-xl">
          <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-gold">Receipt</div>
              <div className="mt-1 text-lg font-extrabold text-text">{receiptNo}</div>
              <div className="text-sm text-text2">
                Sale {saleStatus} · {when(shown.created_at || shown.sale_date)} · business date {when(shown.sale_date).slice(0, 10)}
              </div>
              <div className="text-sm text-text2">{shown.cashier_name || "—"} · {customer}</div>
            </div>
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
          <div className="space-y-4 px-5 py-4 text-sm">
            {saleQ.isError || missing ? (
              <div className="text-err">{missing || "This receipt is unavailable."}</div>
            ) : null}
            <div className="rounded-lg border border-border">
              <div className="grid grid-cols-[1fr_auto_auto] gap-2 border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
                <span>Item</span><span className="text-right">Qty</span><span className="text-right">Amount</span>
              </div>
              {saleQ.isLoading ? <div className="px-3 py-3 text-text2">Loading the receipt…</div> : null}
              {!saleQ.isLoading && itemRows.length === 0 ? (
                <div className="px-3 py-3 text-text2">No product lines are stored on this receipt.</div>
              ) : itemRows.map((line, index) => (
                <div key={index} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 border-b border-border px-3 py-2 last:border-0">
                  <div>
                    <div className="font-semibold text-text">{line.product_name || "Product"}</div>
                    <div className="text-xs text-text2">{money(line.unit_price)} each{line.sku ? ` · ${line.sku}` : ""}</div>
                  </div>
                  <div className="text-right tabular-nums text-text">{line.quantity}</div>
                  <div className="text-right font-semibold tabular-nums text-gold">{money(line.total)}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between rounded-lg border border-border bg-panel px-4 py-3">
              <span className="text-sm text-text2">Receipt total</span>
              <span className="text-xl font-extrabold tabular-nums text-gold">{money(shown.total)}</span>
            </div>
            <PaymentBreakdown payments={payments} />
            <div className="rounded-lg border border-border px-3 py-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-text2">Request</div>
              <div className="mt-1 font-semibold text-text">{status || "—"} · {requester || "—"} · {when(submittedAt)}</div>
              <div className="mt-1">Reason <span className="font-semibold text-text">{reason || "—"}</span></div>
            </div>
            {note ? <div className="text-err">{note}</div> : null}
            {children ? <div className="border-t border-border pt-4">{children}</div> : null}
          </div>
        </Card>
      </div>
    </div>
  );
}
