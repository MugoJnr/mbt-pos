import { useState } from "react";
import { toast } from "sonner";
import { Button, Input } from "@/components/ui-kit";
import { GET, POST, getUser } from "@/lib/api";

type Receipt = {
  id: number;
  supplier_id?: number;
  status?: string;
  payment_status?: string;
  reference?: string;
  reference_note?: string;
  notes?: string;
  due_date?: string;
  lines?: { product_id?: number; product_name?: string; quantity?: number; returned_qty?: number }[];
};

function roleOf() {
  return String(getUser()?.role || "").toLowerCase();
}

export function DeliveryActions({
  receipt,
  onChanged,
}: {
  receipt: Receipt;
  onChanged: (next: Receipt) => void;
}) {
  const role = roleOf();
  const raw = getUser()?.effective_permissions;
  const list = Array.isArray(raw) ? raw.map(String) : null;
  const admin = list ? list.includes("supplier.manage") : role === "admin" || role === "superadmin";
  const canPay = list ? list.includes("supplier.pay") : ["cashier", "manager", "admin", "superadmin"].includes(role);
  const canRequest = list ? list.includes("supplier.request") && !admin : role === "cashier" || role === "manager";
  const open = receipt.status !== "reversed" && receipt.payment_status !== "VOIDED";
  const [payAmount, setPayAmount] = useState("");
  const [reference, setReference] = useState(receipt.reference || receipt.reference_note || "");
  const [notes, setNotes] = useState(receipt.notes || "");
  const [due, setDue] = useState(receipt.due_date || "");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const lines = (receipt.lines || []).filter((line) => {
    const left = Number(line.quantity || 0) - Number(line.returned_qty || 0);
    return left > 0.0001;
  });

  async function reload() {
    const full = await GET<Receipt>(`/stock-receipts/${receipt.id}`);
    if (full?.id) onChanged(full);
  }

  async function run(path: string, body: Record<string, unknown>) {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await POST<any>(path, body);
      if (!saved?.success) {
        toast.error(saved?.error || "That was not saved.");
        return;
      }
      setPin("");
      setReason("");
      setQty("");
      setPayAmount("");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  if (!open && !canPay) return null;

  return (
    <div className="mt-3 space-y-3">
      {canPay && open && receipt.payment_status !== "PAID" ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-semibold text-text2">
            Pay this invoice
            <Input aria-label="Payment amount" type="number" min={0} step={0.01} value={payAmount} onChange={(e) => setPayAmount(e.target.value)} className="mt-1 h-11 w-40" />
          </label>
          <Button
            disabled={busy}
            onClick={() => {
              const amount = Number(payAmount);
              if (!receipt.supplier_id || !Number.isFinite(amount) || amount <= 0) return;
              void run("/supplier-payments", {
                supplier_id: receipt.supplier_id,
                amount,
                method: "cash",
                mode: "manual",
                allocations: [{ receipt_id: receipt.id, amount }],
              });
            }}
          >
            Record payment
          </Button>
        </div>
      ) : null}
      {admin && open ? (
        <div className="grid gap-2 md:grid-cols-2">
          <Input aria-label="Invoice reference" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Invoice reference" />
          <Input aria-label="Delivery note" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Delivery note" />
          <Input aria-label="Due date" value={due} onChange={(e) => setDue(e.target.value)} placeholder="Due YYYY-MM-DD" />
          <Input aria-label="Effective date" value={date} onChange={(e) => setDate(e.target.value)} placeholder="Backdate YYYY-MM-DD" />
          <Input aria-label="Delivery reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for void, backdate, or return" />
          {role !== "superadmin" ? (
            <Input aria-label="Super-Admin PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="Super-Admin PIN for void or return" />
          ) : null}
          <div className="flex flex-wrap gap-2 md:col-span-2">
            <Button variant="secondary" disabled={busy} onClick={() => void run(`/stock-receipts/${receipt.id}/header`, { reference, notes, due_date: due })}>Edit details</Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(`/stock-receipts/${receipt.id}/backdate`, { effective_date: date, reason })}>Backdate</Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(`/stock-receipts/${receipt.id}/reverse`, { reason, pin })}>Void</Button>
          </div>
          {lines.length ? (
            <div className="flex flex-wrap items-end gap-2 md:col-span-2">
              <label className="text-xs font-semibold text-text2">
                Return to supplier
                <select
                  aria-label="Product to return"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  className="mt-1 h-11 rounded-lg border border-border bg-card px-3 text-sm text-text"
                >
                  <option value="">Product</option>
                  {lines.map((line) => (
                    <option key={line.product_id} value={line.product_id}>
                      {line.product_name} · {Number(line.quantity || 0) - Number(line.returned_qty || 0)} left
                    </option>
                  ))}
                </select>
              </label>
              <Input aria-label="Return quantity" type="number" min={0} step={0.0001} value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Qty" className="h-11 w-28" />
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => {
                  if (!productId || Number(qty) <= 0) return;
                  void run(`/stock-receipts/${receipt.id}/lines/${productId}/return`, { quantity: Number(qty), reason, pin });
                }}
              >
                Return
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {canRequest && open ? (
        <div className="flex flex-wrap items-end gap-2">
          <Input aria-label="Requested date" value={date} onChange={(e) => setDate(e.target.value)} placeholder="Requested date YYYY-MM-DD" className="h-11 w-56" />
          <Input aria-label="Request reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" className="h-11 w-56" />
          <Button variant="secondary" disabled={busy} onClick={() => void run(`/stock-receipts/${receipt.id}/requests`, { kind: "backdate", requested_date: date, reason })}>Request backdate</Button>
          <Button variant="secondary" disabled={busy} onClick={() => void run(`/stock-receipts/${receipt.id}/requests`, { kind: "void", reason })}>Request void</Button>
        </div>
      ) : null}
    </div>
  );
}
