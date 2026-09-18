import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, PackagePlus, Pencil, Plus, Truck, X } from "lucide-react";
import { toast } from "sonner";
import { GET, POST, PUT } from "@/lib/api";
import { Button, Card, Input, SectionTitle, Table } from "@/components/ui-kit";
import { KES, todayISO } from "@/lib/format";

type Product = {
  id: number;
  name: string;
  sku?: string;
  cost_price?: number;
  stock?: number;
};

type Props = {
  products: Product[];
  currency: string;
  canReceive: boolean;
  onStockChanged: () => void;
};

export function SupplierDeliveries({
  products,
  currency,
  canReceive,
  onStockChanged,
}: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"deliveries" | "suppliers">("deliveries");
  const [receiving, setReceiving] = useState(false);
  const [supplierDraft, setSupplierDraft] = useState<any | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const suppliersQ = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => GET<any[]>("/suppliers"),
  });
  const purchasesQ = useQuery({
    queryKey: ["purchases"],
    queryFn: () => GET<any[]>("/purchases", { limit: "300" }),
  });
  const suppliers = Array.isArray(suppliersQ.data) ? suppliersQ.data : [];
  const purchases = Array.isArray(purchasesQ.data) ? purchasesQ.data : [];

  function refresh() {
    qc.invalidateQueries({ queryKey: ["purchases"] });
    qc.invalidateQueries({ queryKey: ["suppliers"] });
    onStockChanged();
  }

  return (
    <Card className="mt-5 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4">
        <div>
          <SectionTitle>Supplier receiving</SectionTitle>
          <p className="mt-1 text-xs text-text2">
            One vendor delivery remains one GRN, even when it contains many products.
          </p>
        </div>
        {canReceive ? (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setSupplierDraft({ id: 0 })}>
              <Plus className="h-4 w-4" /> Register supplier
            </Button>
            <Button onClick={() => setReceiving(true)}>
              <PackagePlus className="h-4 w-4" /> Receive delivery
            </Button>
          </div>
        ) : null}
      </div>
      <div className="flex gap-1 border-b border-border bg-panel/40 px-4 pt-3">
        {(["deliveries", "suppliers"] as const).map((name) => (
          <button
            key={name}
            className={`rounded-t-md px-4 py-2 text-xs font-semibold capitalize ${
              tab === name ? "bg-card text-gold" : "text-text2"
            }`}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "deliveries" ? (
        <Table head={["GRN", "Date", "Supplier", "Vendor reference", "Payment", "Lines", "Units", "Total", "Received by", ""]}>
          {purchases.map((p: any) => (
            <tr key={p.id}>
              <td className="px-4 py-2.5 font-mono text-xs font-semibold text-text">{p.purchase_number}</td>
              <td className="px-4 py-2.5 text-text2">{p.delivery_date}</td>
              <td className="px-4 py-2.5 text-text">{p.supplier_name}</td>
              <td className="px-4 py-2.5 text-text2">{p.reference || "—"}</td>
              <td className="px-4 py-2.5 capitalize text-text2">{p.payment_method || "credit"}</td>
              <td className="px-4 py-2.5 tabular-nums">{p.line_count}</td>
              <td className="px-4 py-2.5 tabular-nums">{p.total_units}</td>
              <td className="px-4 py-2.5 font-semibold tabular-nums">{KES(p.total, currency)}</td>
              <td className="px-4 py-2.5 text-text2">{p.received_by_name || "—"}</td>
              <td className="px-4 py-2.5">
                <Button size="sm" variant="ghost" onClick={() => setDetailId(Number(p.id))}>
                  <Eye className="h-3.5 w-3.5" /> View
                </Button>
              </td>
            </tr>
          ))}
        </Table>
      ) : (
        <Table head={["Supplier", "Phone", "Email", "Address", "Notes", ...(canReceive ? [""] : [])]}>
          {suppliers.map((s: any) => (
            <tr key={s.id}>
              <td className="px-4 py-2.5 font-medium text-text">{s.name}</td>
              <td className="px-4 py-2.5 text-text2">{s.phone || "—"}</td>
              <td className="px-4 py-2.5 text-text2">{s.email || "—"}</td>
              <td className="px-4 py-2.5 text-text2">{s.address || "—"}</td>
              <td className="px-4 py-2.5 text-text2">{s.notes || "—"}</td>
              {canReceive ? (
                <td className="px-4 py-2.5">
                  <Button size="sm" variant="ghost" onClick={() => setSupplierDraft(s)}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                </td>
              ) : null}
            </tr>
          ))}
        </Table>
      )}
      {!purchasesQ.isLoading && tab === "deliveries" && !purchases.length ? (
        <div className="py-10 text-center text-sm text-text2">No supplier deliveries recorded yet.</div>
      ) : null}
      {!suppliersQ.isLoading && tab === "suppliers" && !suppliers.length ? (
        <div className="py-10 text-center text-sm text-text2">No suppliers registered yet.</div>
      ) : null}

      {receiving ? (
        <ReceiveDeliveryModal
          products={products}
          suppliers={suppliers}
          currency={currency}
          onClose={() => setReceiving(false)}
          onDone={() => {
            setReceiving(false);
            refresh();
          }}
          onAddSupplier={() => setSupplierDraft({ id: 0 })}
          onProductCreated={() => qc.invalidateQueries({ queryKey: ["products"] })}
        />
      ) : null}
      {supplierDraft ? (
        <SupplierModal
          supplier={supplierDraft}
          onClose={() => setSupplierDraft(null)}
          onDone={() => {
            setSupplierDraft(null);
            qc.invalidateQueries({ queryKey: ["suppliers"] });
          }}
        />
      ) : null}
      {detailId != null ? (
        <DeliveryDetailModal
          purchaseId={detailId}
          currency={currency}
          onClose={() => setDetailId(null)}
        />
      ) : null}
    </Card>
  );
}

function ReceiveDeliveryModal({
  products,
  suppliers,
  currency,
  onClose,
  onDone,
  onAddSupplier,
  onProductCreated,
}: {
  products: Product[];
  suppliers: any[];
  currency: string;
  onClose: () => void;
  onDone: () => void;
  onAddSupplier: () => void;
  onProductCreated: () => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [reference, setReference] = useState("");
  const [deliveryDate, setDeliveryDate] = useState(todayISO());
  const [paymentMethod, setPaymentMethod] = useState("credit");
  const [notes, setNotes] = useState("");
  const [clientTxnId] = useState(
    () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
  );
  const [lines, setLines] = useState([{ key: 1, product_id: "", quantity: "", unit_cost: "" }]);
  const [busy, setBusy] = useState(false);
  /** Products registered inside this delivery, selectable before the catalogue refetch lands. */
  const [justCreated, setJustCreated] = useState<Product[]>([]);
  const [newProductFor, setNewProductFor] = useState<number | null>(null);
  const options = useMemo(
    () => [...products, ...justCreated.filter((c) => !products.some((p) => p.id === c.id))],
    [products, justCreated],
  );
  const total = useMemo(
    () => lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_cost || 0), 0),
    [lines],
  );
  function patchLine(key: number, values: Record<string, string>) {
    setLines((current) => current.map((line) => line.key === key ? { ...line, ...values } : line));
  }
  function selectProduct(key: number, productId: string) {
    const product = options.find((p) => p.id === Number(productId));
    patchLine(key, {
      product_id: productId,
      unit_cost: product?.cost_price ? String(product.cost_price) : "",
    });
  }
  async function submit() {
    if (!supplierId) {
      toast.error("Select or register the supplier");
      return;
    }
    const items = lines
      .filter((line) => line.product_id || line.quantity || line.unit_cost)
      .map((line) => ({
        product_id: Number(line.product_id),
        quantity: Number(line.quantity),
        unit_cost: Number(line.unit_cost),
      }));
    if (!items.length || items.some((line) => !line.product_id || line.quantity <= 0 || line.unit_cost <= 0)) {
      toast.error("Every delivery line needs product, quantity and buying cost");
      return;
    }
    setBusy(true);
    const res = await POST<any>("/purchases", {
      client_txn_id: clientTxnId,
      supplier_id: Number(supplierId),
      reference,
      delivery_date: deliveryDate,
      payment_method: paymentMethod,
      notes,
      items,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(`${res.purchase_number} received as one delivery · ${KES(res.total, currency)}`);
      onDone();
    } else {
      toast.error(res?.error || "Delivery could not be received");
    }
  }
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/65 p-4">
      <div className="max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-xl border border-border bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-text">Receive supplier delivery</h3>
            <p className="text-sm text-text2">All lines save together under one goods-received number.</p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs font-medium text-text2">
            Supplier
            <div className="mt-1 flex gap-1">
              <select className="min-h-[40px] flex-1 rounded-md border border-border bg-panel px-3 text-sm text-text" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                <option value="">Select supplier…</option>
                {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <Button size="sm" variant="secondary" onClick={onAddSupplier}>New</Button>
            </div>
          </label>
          <label className="text-xs font-medium text-text2">
            Vendor invoice / reference
            <Input className="mt-1" value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-text2">
            Delivery date
            <Input className="mt-1" type="date" value={deliveryDate} onChange={(e) => setDeliveryDate(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-text2">
            Payment
            <select className="mt-1 min-h-[40px] w-full rounded-md border border-border bg-panel px-3 text-sm text-text" value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
              <option value="credit">Supplier credit / unpaid</option>
              <option value="cash">Paid cash</option>
              <option value="mpesa">Paid M-Pesa</option>
              <option value="bank">Paid bank</option>
              <option value="card">Paid card</option>
            </select>
          </label>
        </div>
        <div className="space-y-2">
          {lines.map((line, index) => (
            <div key={line.key} className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[38px_1fr_130px_160px_44px] sm:items-end">
              <span className="pb-2 text-xs text-text2">{index + 1}</span>
              <label className="text-xs font-medium text-text2">
                Product
                <div className="mt-1 flex gap-1">
                  <select className="min-h-[40px] flex-1 rounded-md border border-border bg-panel px-3 text-sm text-text" value={line.product_id} onChange={(e) => selectProduct(line.key, e.target.value)}>
                    <option value="">Select product…</option>
                    {options.map((p) => <option key={p.id} value={p.id}>{p.name}{p.sku ? ` · ${p.sku}` : ""}</option>)}
                  </select>
                  <Button size="sm" variant="secondary" onClick={() => setNewProductFor(line.key)}>New</Button>
                </div>
              </label>
              <label className="text-xs font-medium text-text2">
                Quantity
                <Input className="mt-1" type="number" min="0.0001" step="0.01" value={line.quantity} onChange={(e) => patchLine(line.key, { quantity: e.target.value })} />
              </label>
              <label className="text-xs font-medium text-text2">
                Buy price each
                <Input className="mt-1" type="number" min="0.01" step="0.01" value={line.unit_cost} onChange={(e) => patchLine(line.key, { unit_cost: e.target.value })} />
              </label>
              <Button size="sm" variant="ghost" disabled={lines.length === 1} onClick={() => setLines(lines.filter((x) => x.key !== line.key))}><X className="h-4 w-4" /></Button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setLines([...lines, { key: Math.max(...lines.map((x) => x.key)) + 1, product_id: "", quantity: "", unit_cost: "" }])}>
            <Plus className="h-4 w-4" /> Add product line
          </Button>
        </div>
        <p className="mt-2 text-xs text-text2">
          First-time item? Use <span className="text-text">New</span> beside the product. The buying
          price you enter on the line becomes that product's latest cost — you never type it twice.
        </p>
        <label className="mt-4 block text-xs font-medium text-text2">
          Delivery notes
          <Input className="mt-1" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="mt-5 flex items-center justify-between border-t border-border pt-4">
          <div><span className="text-xs text-text2">Delivery total</span><p className="text-xl font-bold text-gold">{KES(total, currency)}</p></div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button onClick={submit} disabled={busy}><Truck className="h-4 w-4" /> Receive all as one</Button>
          </div>
        </div>
        {newProductFor != null ? (
          <NewProductInline
            suggestedCost={lines.find((l) => l.key === newProductFor)?.unit_cost || ""}
            onClose={() => setNewProductFor(null)}
            onCreated={(product, unitCost) => {
              setJustCreated((current) => [...current, product]);
              patchLine(newProductFor, {
                product_id: String(product.id),
                unit_cost: String(unitCost),
              });
              setNewProductFor(null);
              onProductCreated();
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

/** First-time item registered inside a delivery: one buying price, used for the
 *  product's latest cost and this delivery line. */
function NewProductInline({
  suggestedCost,
  onClose,
  onCreated,
}: {
  suggestedCost: string;
  onClose: () => void;
  onCreated: (product: Product, unitCost: number) => void;
}) {
  const [form, setForm] = useState({
    name: "",
    sku: "",
    unit: "pcs",
    price: "",
    cost_price: suggestedCost,
  });
  const [busy, setBusy] = useState(false);

  async function submit() {
    const name = form.name.trim();
    const price = Number(form.price || 0);
    const cost = Number(form.cost_price || 0);
    if (!name) {
      toast.error("Product name is required");
      return;
    }
    if (price <= 0 || cost <= 0) {
      toast.error("Enter both a buying price and a selling price above zero");
      return;
    }
    setBusy(true);
    const res = await POST<any>("/products", {
      name,
      sku: form.sku.trim(),
      unit: form.unit.trim() || "pcs",
      price,
      cost_price: cost,
    });
    setBusy(false);
    if (res?.id != null) {
      toast.success(`${name} registered · added to this delivery`);
      onCreated({ id: Number(res.id), name, sku: form.sku.trim(), cost_price: cost }, cost);
    } else {
      toast.error(res?.error || "Product could not be registered");
    }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-2xl">
        <h4 className="text-base font-semibold text-text">Register first-time product</h4>
        <p className="mt-1 text-xs text-text2">
          The buying price below is saved once: it becomes this product's latest cost and the
          buying price on this delivery line.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {([
            ["name", "Product name", "text"],
            ["sku", "SKU / code", "text"],
            ["unit", "Unit", "text"],
            ["cost_price", "Buying price each", "number"],
            ["price", "Selling price", "number"],
          ] as const).map(([key, label, type]) => (
            <label key={key} className="text-xs font-medium text-text2">
              {label}
              <Input
                className="mt-1"
                type={type}
                min={type === "number" ? "0.01" : undefined}
                step={type === "number" ? "0.01" : undefined}
                value={(form as any)[key] ?? ""}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy}>Register &amp; add to delivery</Button>
        </div>
      </div>
    </div>
  );
}

function SupplierModal({ supplier, onClose, onDone }: { supplier: any; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "", notes: "", ...supplier });
  const [busy, setBusy] = useState(false);
  const isNew = !form.id;
  async function submit() {
    if (!String(form.name || "").trim()) {
      toast.error("Supplier name is required");
      return;
    }
    setBusy(true);
    const payload = { name: form.name.trim(), phone: form.phone, email: form.email, address: form.address, notes: form.notes };
    const res = isNew ? await POST<any>("/suppliers", payload) : await PUT<any>(`/suppliers/${form.id}`, payload);
    setBusy(false);
    if (res?.success) {
      toast.success(isNew ? "Supplier registered" : "Supplier updated");
      onDone();
    } else toast.error(res?.error || "Supplier save failed");
  }
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 p-4">
      <div className="w-full max-w-xl rounded-xl border border-border bg-card p-5 shadow-2xl">
        <h3 className="mb-4 text-lg font-semibold text-text">{isNew ? "Register supplier" : "Edit supplier"}</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["name", "Supplier name"], ["phone", "Phone"], ["email", "Email"],
            ["address", "Address"], ["notes", "Notes"],
          ].map(([key, label]) => (
            <label key={key} className="text-xs font-medium text-text2">{label}
              <Input className="mt-1" value={form[key] || ""} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </label>
          ))}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy}>Save supplier</Button>
        </div>
      </div>
    </div>
  );
}

function DeliveryDetailModal({ purchaseId, currency, onClose }: { purchaseId: number; currency: string; onClose: () => void }) {
  const detailQ = useQuery({
    queryKey: ["purchase", purchaseId],
    queryFn: () => GET<any>(`/purchases/${purchaseId}`),
  });
  const purchase = detailQ.data?.purchase || {};
  const items = Array.isArray(purchase.items) ? purchase.items : [];
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/65 p-4">
      <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-xl border border-border bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <div><h3 className="text-lg font-semibold text-text">{purchase.purchase_number || "Supplier delivery"}</h3>
            <p className="text-sm text-text2">{purchase.supplier_name} · {purchase.delivery_date} · ref {purchase.reference || "—"} · {purchase.payment_method || "credit"}</p></div>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
        <Table head={["Product", "Qty", "Buy price", "Line total", "Stock before", "Stock after"]}>
          {items.map((line: any) => (
            <tr key={line.id}>
              <td className="px-4 py-2.5 font-medium text-text">{line.product_name}</td>
              <td className="px-4 py-2.5 tabular-nums">{line.quantity}</td>
              <td className="px-4 py-2.5 tabular-nums">{KES(line.unit_cost, currency)}</td>
              <td className="px-4 py-2.5 font-semibold tabular-nums">{KES(line.total, currency)}</td>
              <td className="px-4 py-2.5 tabular-nums text-text2">{line.qty_before}</td>
              <td className="px-4 py-2.5 tabular-nums text-text">{line.qty_after}</td>
            </tr>
          ))}
        </Table>
        <div className="mt-4 text-right text-lg font-bold text-gold">Total {KES(purchase.total, currency)}</div>
        {purchase.notes ? <p className="mt-3 text-sm text-text2">Notes: {purchase.notes}</p> : null}
      </div>
    </div>
  );
}
