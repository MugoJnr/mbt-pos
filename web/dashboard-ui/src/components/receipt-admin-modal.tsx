import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Ban, Printer, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { GET, POST } from "@/lib/api";
import { Button, Input, Table } from "@/components/ui-kit";
import { KES } from "@/lib/format";

type Props = {
  saleId: number;
  currency: string;
  onClose: () => void;
  onChanged: () => void;
};

const esc = (value: unknown) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

export function ReceiptAdminModal({ saleId, currency, onClose, onChanged }: Props) {
  const detailQ = useQuery({
    queryKey: ["sale-receipt", saleId],
    queryFn: () => GET<any>(`/sales/${saleId}/receipt`),
  });
  const data = detailQ.data || {};
  const sale = data.sale || {};
  const lines = Array.isArray(data.lines) ? data.lines : [];
  const payments = Array.isArray(data.payments) ? data.payments : [];
  const [action, setAction] = useState<"void" | "return" | null>(null);
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [refundMethod, setRefundMethod] = useState("cash");
  const [returnQty, setReturnQty] = useState<Record<number, string>>({});
  const [forcePayments, setForcePayments] = useState(false);
  const [creditWarning, setCreditWarning] = useState("");
  const [busy, setBusy] = useState(false);

  const paymentDisplay = useMemo(() => {
    if (payments.length) {
      return payments
        .map((p: any) => `${p.payment_method || p.method}: ${KES(p.amount, currency)}`)
        .join(" + ");
    }
    const tenders = sale.payment_tenders;
    if (tenders) {
      try {
        const parsed = typeof tenders === "string" ? JSON.parse(tenders) : tenders;
        if (Array.isArray(parsed) && parsed.length) {
          return parsed
            .map((p: any) => `${p.method}: ${KES(p.amount, currency)}`)
            .join(" + ");
        }
      } catch {
        // Fall back to the saved method below.
      }
    }
    return String(sale.payment_method || "—");
  }, [payments, sale.payment_method, sale.payment_tenders, currency]);

  function resetAction(next: "void" | "return" | null) {
    setAction(next);
    setReason("");
    setPin("");
    setForcePayments(false);
    setCreditWarning("");
  }

  async function voidReceipt() {
    if (!reason.trim() || !pin) {
      toast.error("Reason and Super Admin PIN are required");
      return;
    }
    setBusy(true);
    const res = await POST<any>(`/sales/${saleId}/void`, {
      reason: reason.trim(),
      pin,
      force_with_payments: forcePayments,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(res.warning || "Receipt voided and stock restored");
      onChanged();
      onClose();
      return;
    }
    if (res?.error === "credit_payments_exist") {
      setCreditWarning(res.message || "Debt payments exist on this receipt.");
      setForcePayments(true);
      return;
    }
    toast.error(res?.message || res?.error || "Void failed");
  }

  async function returnItems() {
    const items = lines
      .map((line: any) => ({
        sale_item_id: Number(line.id),
        quantity: Number(returnQty[Number(line.id)] || 0),
      }))
      .filter((line: any) => line.quantity > 0);
    if (!items.length || !reason.trim() || !pin) {
      toast.error("Choose a quantity and enter reason plus Super Admin PIN");
      return;
    }
    setBusy(true);
    const res = await POST<any>(`/sales/${saleId}/return`, {
      items,
      reason: reason.trim(),
      refund_method: refundMethod,
      pin,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(
        `Return ${res.return_receipt || ""} recorded · ${KES(res.refund_total || 0, currency)}`,
      );
      onChanged();
      onClose();
    } else {
      toast.error(res?.error || "Return failed");
    }
  }

  function printReceipt() {
    const win = window.open("", "_blank", "width=760,height=850");
    if (!win) {
      toast.error("Allow pop-ups to print this receipt");
      return;
    }
    win.opener = null;
    const rows = lines
      .map(
        (line: any) => `<tr>
          <td>${esc(line.product_name || "Item")}</td>
          <td>${esc(line.quantity)}</td>
          <td>${esc(KES(line.unit_price, currency))}</td>
          <td>${esc(KES(line.discount || 0, currency))}</td>
          <td>${esc(KES(line.total, currency))}</td>
        </tr>`,
      )
      .join("");
    win.document.write(`<!doctype html><html><head><title>${esc(sale.receipt_number)}</title>
      <style>body{font:14px Arial;max-width:720px;margin:32px auto;color:#111}
      h1{font-size:22px}table{width:100%;border-collapse:collapse;margin:20px 0}
      th,td{padding:8px;border-bottom:1px solid #ddd;text-align:right}
      th:first-child,td:first-child{text-align:left}.totals{margin-left:auto;width:280px}
      .totals div{display:flex;justify-content:space-between;padding:4px}
      @media print{button{display:none}}</style></head><body>
      <h1>MBT POS Receipt</h1>
      <p><b>${esc(sale.receipt_number)}</b><br>${esc(sale.created_at)}<br>
      Cashier: ${esc(sale.cashier_name || "—")}<br>Payment: ${esc(paymentDisplay)}</p>
      <table><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Discount</th><th>Total</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="totals"><div><span>Subtotal</span><b>${esc(KES(sale.subtotal, currency))}</b></div>
      <div><span>Discount</span><b>${esc(KES(sale.discount || 0, currency))}</b></div>
      <div><span>Tax</span><b>${esc(KES(sale.tax || 0, currency))}</b></div>
      <div><span>Total</span><b>${esc(KES(sale.total, currency))}</b></div>
      <div><span>Paid</span><b>${esc(KES(sale.amount_paid, currency))}</b></div>
      <div><span>Change</span><b>${esc(KES(sale.change_amount || 0, currency))}</b></div></div>
      <button onclick="window.print()">Print</button></body></html>`);
    win.document.close();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-xl border border-border bg-card shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-border bg-card p-5">
          <div>
            <h2 className="text-lg font-semibold text-text">
              Receipt {sale.receipt_number || `#${saleId}`}
            </h2>
            <p className="mt-1 text-xs text-text2">
              {sale.created_at || "Loading…"} · {sale.cashier_name || "—"}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>

        {detailQ.isLoading ? (
          <div className="p-12 text-center text-text2">Loading the real receipt…</div>
        ) : data.error ? (
          <div className="p-8 text-center text-err">{String(data.error)}</div>
        ) : (
          <div className="space-y-5 p-5">
            <div className="grid gap-3 rounded-lg bg-panel p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <Info label="Status" value={sale.status || "completed"} />
              <Info label="Customer" value={sale.customer_name || "Walk-in"} />
              <Info label="Payment" value={paymentDisplay} />
              <Info label="Total" value={KES(sale.total, currency)} />
              <Info label="Subtotal" value={KES(sale.subtotal, currency)} />
              <Info label="Discount" value={KES(sale.discount || 0, currency)} />
              <Info label="Amount paid" value={KES(sale.amount_paid, currency)} />
              <Info label="Change" value={KES(sale.change_amount || 0, currency)} />
            </div>

            <div className="overflow-hidden rounded-lg border border-border">
              <Table head={["Item", "SKU", "Qty", "Returned", "Price", "Discount", "Total"]}>
                {lines.map((line: any) => (
                  <tr key={line.id}>
                    <td className="px-4 py-2.5 font-medium text-text">{line.product_name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text2">{line.sku || "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{line.quantity}</td>
                    <td className="px-4 py-2.5 tabular-nums text-text2">{line.returned_qty || 0}</td>
                    <td className="px-4 py-2.5 tabular-nums">{KES(line.unit_price, currency)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{KES(line.discount || 0, currency)}</td>
                    <td className="px-4 py-2.5 tabular-nums font-semibold">{KES(line.total, currency)}</td>
                  </tr>
                ))}
              </Table>
            </div>

            {data.debt ? (
              <div className="rounded-lg border border-border p-4 text-sm">
                <b>Linked debt {data.debt.invoice_number}</b>
                <span className="ml-2 text-text2">
                  {data.debt.status} · balance {KES(data.debt.balance, currency)}
                </span>
              </div>
            ) : null}

            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="secondary" onClick={printReceipt}>
                <Printer className="h-4 w-4" /> Reprint
              </Button>
              {data.can_return && String(sale.status).toLowerCase() === "completed" ? (
                <Button variant="secondary" onClick={() => resetAction("return")}>
                  <RotateCcw className="h-4 w-4" /> Return items
                </Button>
              ) : null}
              {data.can_void && String(sale.status).toLowerCase() === "completed" ? (
                <Button variant="danger" onClick={() => resetAction("void")}>
                  <Ban className="h-4 w-4" /> Void receipt
                </Button>
              ) : null}
            </div>

            {action === "void" ? (
              <ActionBox title="Void this receipt">
                <p className="text-sm text-text2">
                  Stock, accounting, store credit and linked debt are handled atomically.
                </p>
                {creditWarning ? (
                  <div className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
                    {creditWarning} Confirm again to void while retaining payment history.
                  </div>
                ) : null}
                <Input placeholder="Required reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                <Input placeholder="Super Admin PIN" type="password" autoComplete="off" value={pin} onChange={(e) => setPin(e.target.value)} />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => resetAction(null)}>Cancel</Button>
                  <Button variant="danger" disabled={busy} onClick={voidReceipt}>
                    {forcePayments ? "Confirm void" : "Void receipt"}
                  </Button>
                </div>
              </ActionBox>
            ) : null}

            {action === "return" ? (
              <ActionBox title="Return receipt items">
                {lines.filter((line: any) => Number(line.remaining_qty || 0) > 0).map((line: any) => (
                  <label key={line.id} className="grid grid-cols-[1fr_120px] items-center gap-3 text-sm">
                    <span>{line.product_name} · available {line.remaining_qty}</span>
                    <Input
                      type="number" min="0" max={line.remaining_qty} step="0.01"
                      value={returnQty[Number(line.id)] || ""}
                      onChange={(e) => setReturnQty({ ...returnQty, [Number(line.id)]: e.target.value })}
                      placeholder="Qty"
                    />
                  </label>
                ))}
                <select className="w-full rounded-md border border-border bg-panel px-3 py-2 text-sm" value={refundMethod} onChange={(e) => setRefundMethod(e.target.value)}>
                  <option value="cash">Cash refund</option>
                  <option value="mpesa">M-Pesa refund</option>
                  <option value="bank">Bank refund</option>
                  <option value="card">Card refund</option>
                </select>
                <Input placeholder="Required return reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                <Input placeholder="Super Admin PIN" type="password" autoComplete="off" value={pin} onChange={(e) => setPin(e.target.value)} />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => resetAction(null)}>Cancel</Button>
                  <Button disabled={busy} onClick={returnItems}>Process return</Button>
                </div>
              </ActionBox>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: unknown }) {
  return <div><p className="text-xs text-text2">{label}</p><p className="mt-1 font-medium text-text">{String(value || "—")}</p></div>;
}

function ActionBox({ title, children }: { title: string; children: ReactNode }) {
  return <div className="space-y-3 rounded-lg border border-border bg-panel/60 p-4"><h3 className="font-semibold text-text">{title}</h3>{children}</div>;
}
