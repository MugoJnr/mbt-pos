import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, RefreshCw, Package, Download } from "lucide-react";
import { ProductPhoto } from "@/components/product-photo";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { DEL, GET, POST, PUT, getToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApi, exportQuery } from "@/lib/download";
import { KES, todayISO } from "@/lib/format";
import { nameMatches } from "@/lib/name-search";
import { wheelStep } from "@/lib/wheel-steps";

export const Route = createFileRoute("/inventory")({
  component: Inventory,
});

type Product = {
  id: number;
  name: string;
  sku?: string;
  barcode?: string;
  category?: string;
  price: number;
  cost_price?: number;
  stock: number;
  min_stock?: number;
  unit?: string;
  image_path?: string;
  is_active?: number;
};

type SortKey = "name" | "stock" | "price" | "category";

type StockReceipt = {
  id: number;
  product_id?: number;
  product_name?: string;
  sku?: string;
  barcode?: string;
  category?: string;
  unit?: string;
  price?: number;
  qty_before?: number;
  qty_change?: number;
  qty_after?: number;
  current_stock?: number;
  min_stock?: number;
  cost_price?: number;
  reason?: string;
  username?: string;
  created_at?: string;
  supplier_name?: string;
  supplier_phone?: string;
  supplier_notes?: string;
  receipt_number?: string;
  grand_total?: number;
  grouped?: boolean;
  lines?: {
    product_name?: string;
    quantity?: number;
    unit_cost?: number;
    line_total?: number;
    unit?: string;
    sku?: string;
  }[];
};

function Inventory() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const canAdjust = role === "superadmin";
  const canEdit = ["cashier", "viewer", "manager", "admin", "superadmin"].includes(role);
  const canRemove = role === "admin" || role === "superadmin";
  const canReceive = ["cashier", "manager", "admin", "superadmin"].includes(role);
  const [adjId, setAdjId] = useState("");
  const [adjDir, setAdjDir] = useState("add");
  const [adjQty, setAdjQty] = useState("1");
  const [adjReason, setAdjReason] = useState("Correction");
  const [adjMsg, setAdjMsg] = useState("");
  const [adjPin, setAdjPin] = useState("");
  const [reviewPin, setReviewPin] = useState("");
  const seeCost = role !== "cashier" && role !== "viewer";
  const showStockValue = ["manager", "admin", "superadmin"].includes(role);
  const [recvId, setRecvId] = useState("");
  const [recvQty, setRecvQty] = useState("1");
  const [recvSupplier, setRecvSupplier] = useState("");
  const [recvName, setRecvName] = useState("");
  const [recvPhone, setRecvPhone] = useState("");
  const [recvSupplierNotes, setRecvSupplierNotes] = useState("");
  const [recvNotes, setRecvNotes] = useState("");
  const [recvPin, setRecvPin] = useState("");
  const [recvMsg, setRecvMsg] = useState("");
  const [recvBusy, setRecvBusy] = useState(false);
  const recvTokenRef = useRef("");
  const [recvLines, setRecvLines] = useState<
    { product_id: number; name: string; quantity: number; unit_cost: number | null }[]
  >([]);
  const [recvCost, setRecvCost] = useState("");
  const [productDetail, setProductDetail] = useState<Product | null>(null);
  const [editId, setEditId] = useState("");
  const [editForm, setEditForm] = useState({
    name: "", sku: "", barcode: "", category: "", price: "", cost_price: "",
    unit: "pcs", min_stock: "5", is_active: "1",
  });
  const [editMsg, setEditMsg] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newProduct, setNewProduct] = useState({
    name: "", sku: "", category: "", price: "", cost_price: "", stock: "0", unit: "pcs", barcode: "",
  });
  const [newPhoto, setNewPhoto] = useState<File | null>(null);
  const [newPhotoUrl, setNewPhotoUrl] = useState("");
  const [savingProduct, setSavingProduct] = useState(false);
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [receipt, setReceipt] = useState<StockReceipt | null>(null);
  const pageSize = 40;

  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const requestsQ = useQuery({
    queryKey: ["adjustment-requests"],
    queryFn: () => GET<Record<string, any>[]>("/stock-adjustment-requests?status=pending"),
    enabled: canReceive,
  });
  const suppliersQ = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => GET<{ id: number; name?: string; phone?: string; notes?: string }[]>("/suppliers"),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";
  const adjustStep = wheelStep(settingsQ.data, "wheel_stock_adjust");
  const receiveStep = wheelStep(settingsQ.data, "wheel_receive_qty");
  const qtyStep = wheelStep(settingsQ.data, "wheel_dashboard_qty");
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const suppliers = Array.isArray(suppliersQ.data) ? suppliersQ.data : [];
  const selectedProduct = products.find((p) => String(p.id) === adjId);

  const list = useMemo(() => {
    const filtered = products.filter((p) => nameMatches(q, p.name));
    filtered.sort((a, b) => {
      let av: string | number = a[sortKey] as any;
      let bv: string | number = b[sortKey] as any;
      if (sortKey === "stock" || sortKey === "price") {
        av = Number(av || 0);
        bv = Number(bv || 0);
      } else {
        av = String(av || "").toLowerCase();
        bv = String(bv || "").toLowerCase();
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return filtered;
  }, [products, q, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(list.length / pageSize));
  const pageRows = list.slice(page * pageSize, page * pageSize + pageSize);

  const totalValue = products.reduce(
    (s, p) => s + Number(p.stock || 0) * Number(p.cost_price || 0),
    0,
  );
  const lowCount = products.filter(
    (p) => Number(p.stock) > 0 && Number(p.stock) <= Number(p.min_stock ?? 5),
  ).length;

  function loadEdit(p: Product) {
    setEditId(String(p.id));
    setEditForm({
      name: p.name || "",
      sku: p.sku || "",
      barcode: p.barcode || "",
      category: p.category || "",
      price: String(p.price ?? ""),
      cost_price: String(p.cost_price ?? ""),
      unit: p.unit || "pcs",
      min_stock: String(p.min_stock ?? 5),
      is_active: Number(p.is_active ?? 1) === 0 ? "0" : "1",
    });
    setEditMsg("");
  }

  async function saveEdit() {
    setEditMsg("");
    if (!editId) {
      setEditMsg("Select a product.");
      return;
    }
    if (!editForm.name.trim()) {
      setEditMsg("Product name is required.");
      return;
    }
    const price = Number(editForm.price);
    if (!Number.isFinite(price) || price < 0) {
      setEditMsg("Enter a selling price of zero or more.");
      return;
    }
    const body: Record<string, unknown> = {
      name: editForm.name.trim(),
      sku: editForm.sku.trim(),
      barcode: editForm.barcode.trim(),
      category: editForm.category.trim(),
      price,
      unit: editForm.unit.trim() || "pcs",
      min_stock: Number(editForm.min_stock || 0),
    };
    if (canRemove) body.is_active = editForm.is_active === "0" ? 0 : 1;
    if (seeCost) {
      const cost = Number(editForm.cost_price || 0);
      if (!Number.isFinite(cost) || cost < 0) {
        setEditMsg("Enter a cost of zero or more.");
        return;
      }
      body.cost_price = cost;
    }
    setEditBusy(true);
    try {
      const res = await PUT<{ success?: boolean; error?: string }>(`/products/${editId}`, body);
      if (!res?.success) {
        setEditMsg(res?.error || "The product was not saved.");
        return;
      }
      setEditMsg("Product details saved. Stock quantity was not changed.");
      qc.invalidateQueries({ queryKey: ["products"] });
      if (productDetail && String(productDetail.id) === editId) {
        setProductDetail({
          ...productDetail,
          ...body,
          price,
          cost_price: seeCost ? Number(body.cost_price) : productDetail.cost_price,
          is_active: Number(body.is_active),
        } as Product);
      }
    } finally {
      setEditBusy(false);
    }
  }

  async function archiveProduct(target?: Product | null) {
    const product = target || products.find((p) => String(p.id) === editId) || productDetail;
    if (!product || !canRemove) return;
    const ok = window.confirm(
      `Remove ${product.name}?\n\nIf it has stock, a receipt, or a stock movement, it leaves the selling list and old receipts keep it. If it has no history, it is deleted.`,
    );
    if (!ok) return;
    const res = await DEL<{ success?: boolean; error?: string }>(`/products/${product.id}`);
    if (!res?.success) {
      toast.error(res?.error || "The product was not archived.");
      return;
    }
    toast.success(res?.message || `${product.name} was removed.`);
    setEditId("");
    setProductDetail(null);
    qc.invalidateQueries({ queryKey: ["products"] });
  }

  const adjustFields = (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <label className="text-xs font-semibold text-text2 md:col-span-2">Name
        <Input aria-label="Product name" className="mt-1 h-11" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Selling price
        <Input aria-label="Selling price" className="mt-1 h-11" type="number" min={0} step="0.01" value={editForm.price} onChange={(e) => setEditForm({ ...editForm, price: e.target.value })} />
      </label>
      {seeCost ? (
        <label className="text-xs font-semibold text-text2">Cost
          <Input aria-label="Cost price" className="mt-1 h-11" type="number" min={0} step="0.01" value={editForm.cost_price} onChange={(e) => setEditForm({ ...editForm, cost_price: e.target.value })} />
        </label>
      ) : null}
      <label className="text-xs font-semibold text-text2">SKU
        <Input aria-label="SKU" className="mt-1 h-11" value={editForm.sku} onChange={(e) => setEditForm({ ...editForm, sku: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Barcode
        <Input aria-label="Barcode" className="mt-1 h-11" value={editForm.barcode} onChange={(e) => setEditForm({ ...editForm, barcode: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Category
        <Input aria-label="Category" className="mt-1 h-11" value={editForm.category} onChange={(e) => setEditForm({ ...editForm, category: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Unit
        <Input aria-label="Unit" className="mt-1 h-11" value={editForm.unit} onChange={(e) => setEditForm({ ...editForm, unit: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Low-stock alert
        <Input aria-label="Low-stock alert" className="mt-1 h-11" type="number" min={0} value={editForm.min_stock} onChange={(e) => setEditForm({ ...editForm, min_stock: e.target.value })} />
      </label>
      {canRemove ? (
      <label className="text-xs font-semibold text-text2">Status
        <select
          aria-label="Product status"
          value={editForm.is_active}
          onChange={(e) => setEditForm({ ...editForm, is_active: e.target.value })}
          className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
        >
          <option value="1">Active</option>
          <option value="0">Inactive</option>
        </select>
      </label>
      ) : null}
    </div>
  );

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "category" ? "asc" : "desc");
    }
    setPage(0);
  }

  async function exportInv(format: "xlsx" | "csv") {
    try {
      setExporting(true);
      const qs = exportQuery({ format, inventory: "1" });
      await downloadApi(`/reports/export?${qs}`, `MBT_Inventory_${todayISO()}.${format}`);
      toast.success(`${format.toUpperCase()} downloaded`);
    } catch (e: any) {
      toast.error(e?.message || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  const sortLabel = (key: SortKey, label: string) => (
    <button type="button" onClick={() => toggleSort(key)} className="hover:text-gold">
      {label} {sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </button>
  );

  return (
    <AppShell title="Inventory">
      {canEdit ? (
        <Card className="mb-3" id="adjust-product">
          <div className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-extrabold text-text">Adjust product</div>
              {canRemove ? (
                <Button variant="danger" disabled={!editId} onClick={() => archiveProduct()}>
                  Remove product
                </Button>
              ) : null}
            </div>
            <div className="text-xs text-text2">
              Change the selling price, cost, name, barcode, category, unit, or low-stock alert.
              Stock quantity is not changed here. Use Adjust stock for the quantity.
            </div>
            <label className="text-xs font-semibold text-text2">
              Product
              <select
                aria-label="Product to adjust"
                value={editId}
                onChange={(e) => {
                  const picked = products.find((p) => String(p.id) === e.target.value);
                  if (picked) loadEdit(picked);
                  else setEditId("");
                }}
                className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
              >
                <option value="">Select a product</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {KES(p.price, currency)}
                  </option>
                ))}
              </select>
            </label>
            {editId ? (
              <>
                {adjustFields}
                <div className="flex flex-wrap gap-2">
                <Button onClick={saveEdit} disabled={editBusy}>
                  {editBusy ? "Saving…" : "Save product details"}
                </Button>
                {canRemove ? (
                  <Button variant="danger" onClick={() => archiveProduct()}>Remove product</Button>
                ) : null}
                </div>
                {editMsg ? <div className="text-sm text-text2">{editMsg}</div> : null}
              </>
            ) : null}
          </div>
        </Card>
      ) : null}
      {canAdjust ? (
        <Card className="mb-3">
          <div className="p-4 space-y-3">
            <div className="text-sm font-extrabold text-text">Adjust stock</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-text2">
                Product
                <select
                  aria-label="Product"
                  value={adjId}
                  onChange={(e) => setAdjId(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
                >
                  <option value="">Select a product</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — stock {p.stock}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-semibold text-text2">
                Adjustment
                <select
                  aria-label="Adjustment"
                  value={adjDir}
                  onChange={(e) => setAdjDir(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
                >
                  <option value="add">Increase stock</option>
                  <option value="remove">Reduce stock</option>
                  <option value="set">Set counted quantity</option>
                </select>
              </label>
              <label className="text-xs font-semibold text-text2">
                Quantity
                <Input
                  aria-label="Quantity"
                  type="number"
                  min={0}
                  step={adjustStep}
                  value={adjQty}
                  onChange={(e) => setAdjQty(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                Reason
                <Input
                  aria-label="Reason"
                  value={adjReason}
                  onChange={(e) => setAdjReason(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              {user?.role === "superadmin" ? (
                <div className="text-xs text-text2">Signed in as Super Admin. No PIN is required.</div>
              ) : (
              <label className="text-xs font-semibold text-text2">
                Super-Admin PIN
                <Input
                  aria-label="Super-Admin PIN"
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  value={adjPin}
                  onChange={(e) => setAdjPin(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              )}
              <div className="text-xs font-semibold text-text2">
                Current stock
                <div id="adj-current-stock" className="mt-1 text-lg font-extrabold text-text">
                  {selectedProduct ? Number(selectedProduct.stock) : "—"}
                </div>
              </div>
            </div>
            <Button
              onClick={async () => {
                setAdjMsg("");
                const qty = Number(adjQty);
                if (!adjId) {
                  setAdjMsg("Select a product.");
                  return;
                }
                if (!Number.isFinite(qty) || qty < 0 || (adjDir !== "set" && qty === 0)) {
                  setAdjMsg("Enter a quantity greater than zero.");
                  return;
                }
                if (user?.role !== "superadmin" && !adjPin.trim()) {
                  setAdjMsg("Super-Admin PIN is required.");
                  return;
                }
                const current = Number(selectedProduct?.stock || 0);
                const newQty =
                  adjDir === "set" ? qty : adjDir === "remove" ? current - qty : current + qty;
                if (newQty < 0) {
                  setAdjMsg("That would take stock below zero.");
                  return;
                }
                const res = await POST<any>(`/products/${adjId}/adjust`, {
                  new_qty: newQty,
                  expected_stock: current,
                  reason: adjReason || "Correction",
                  pin: adjPin,
                });
                if (res?.success) {
                  setAdjMsg(`Stock adjusted: ${res.old_stock} → ${res.new_stock}.`);
                  setAdjPin("");
                  qc.invalidateQueries({ queryKey: ["products"] });
                } else if (res?.current_stock !== undefined) {
                  setAdjMsg("Stock changed. Refresh, review the latest quantity, and submit again.");
                  qc.invalidateQueries({ queryKey: ["products"] });
                } else {
                  setAdjMsg(res?.error || "Adjustment failed");
                }
              }}
            >
              Save adjustment
            </Button>
            {adjMsg ? <div className="text-sm text-text2">{adjMsg}</div> : null}
          </div>
        </Card>
      ) : null}
      {canReceive ? (
        <Card className="mb-3">
          <div className="p-4 space-y-3">
            <div className="text-sm font-extrabold text-text">Receive from supplier</div>
            <div className="text-xs text-text2">
              Add every product on this delivery, then save once. No extra PIN. One receipt covers all of the lines.
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-text2">
                Product
                <select
                  aria-label="Receive product"
                  value={recvId}
                  onChange={(e) => setRecvId(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
                >
                  <option value="">Select a product</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — stock {p.stock}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-semibold text-text2">
                Quantity received
                <Input
                  aria-label="Quantity received"
                  type="number"
                  min={0}
                  step={receiveStep}
                  value={recvQty}
                  onChange={(e) => setRecvQty(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                Supplier
                <select
                  aria-label="Supplier"
                  value={recvSupplier}
                  onChange={(e) => setRecvSupplier(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
                >
                  <option value="">New supplier</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name || `Supplier ${s.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-semibold text-text2">
                Delivery note
                <Input
                  aria-label="Delivery note"
                  value={recvNotes}
                  onChange={(e) => setRecvNotes(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Invoice or delivery note"
                />
              </label>
              {!recvSupplier ? (
                <>
                  <label className="text-xs font-semibold text-text2">
                    New supplier name
                    <Input
                      aria-label="New supplier name"
                      value={recvName}
                      onChange={(e) => setRecvName(e.target.value)}
                      className="mt-1 h-11"
                    />
                  </label>
                  <label className="text-xs font-semibold text-text2">
                    Phone
                    <Input
                      aria-label="Supplier phone"
                      value={recvPhone}
                      onChange={(e) => setRecvPhone(e.target.value)}
                      className="mt-1 h-11"
                    />
                  </label>
                  <label className="text-xs font-semibold text-text2 md:col-span-2">
                    Supplier note
                    <Input
                      aria-label="Supplier note"
                      value={recvSupplierNotes}
                      onChange={(e) => setRecvSupplierNotes(e.target.value)}
                      className="mt-1 h-11"
                    />
                  </label>
                </>
              ) : null}
            </div>
              <label className="text-xs font-semibold text-text2">
                Purchase cost
                <Input
                  aria-label="Purchase cost"
                  type="number"
                  min={0}
                  step={0.01}
                  value={recvCost}
                  onChange={(e) => setRecvCost(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
            <Button
              variant="secondary"
              onClick={() => {
                const qty = Number(recvQty);
                const cost = recvCost.trim() === "" ? null : Number(recvCost);
                if (!recvId || !Number.isFinite(qty) || qty <= 0) {
                  setRecvMsg("Select a product and a quantity before adding a line.");
                  return;
                }
                if (cost !== null && !Number.isFinite(cost)) {
                  setRecvMsg("Enter a valid purchase cost, or leave it blank to keep the current cost.");
                  return;
                }
                if (recvLines.some((line) => line.product_id === Number(recvId))) {
                  setRecvMsg("That product is already on this delivery.");
                  return;
                }
                const product = products.find((p) => p.id === Number(recvId));
                setRecvLines((lines) => [
                  ...lines,
                  { product_id: Number(recvId), name: product?.name || "Product", quantity: qty, unit_cost: cost },
                ]);
                setRecvMsg("");
              }}
            >
              Add product to this delivery
            </Button>
            {recvLines.length ? (
              <div className="text-sm text-text">
                {recvLines.map((line) => (
                  <div key={line.product_id} className="flex items-center justify-between gap-2 py-1">
                    <span>
                      {line.name} · {line.quantity} × {line.unit_cost == null ? "current cost" : line.unit_cost}
                      {line.unit_cost == null ? "" : ` = ${(line.quantity * line.unit_cost).toFixed(2)}`}
                    </span>
                    <button
                      type="button"
                      className="text-xs font-semibold text-err"
                      onClick={() => setRecvLines((lines) => lines.filter((item) => item.product_id !== line.product_id))}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <div className="font-extrabold">
                  Grand total {recvLines.reduce((sum, line) => sum + line.quantity * (line.unit_cost || 0), 0).toFixed(2)}
                </div>
              </div>
            ) : null}
            <Button
              disabled={recvBusy}
              onClick={async () => {
                setRecvMsg("");
                const qty = Number(recvQty);
                if (!recvLines.length && !recvId) {
                  setRecvMsg("Add at least one product.");
                  return;
                }
                if (!recvLines.length && (!Number.isFinite(qty) || qty <= 0)) {
                  setRecvMsg("Enter a quantity greater than zero.");
                  return;
                }
                setRecvBusy(true);
                try {
                  let supplierId = recvSupplier ? Number(recvSupplier) : 0;
                  if (!supplierId) {
                    if (!recvName.trim()) {
                      setRecvMsg("Choose a supplier or enter a new supplier name.");
                      return;
                    }
                    const created = await POST<any>("/suppliers", {
                      name: recvName.trim(),
                      phone: recvPhone.trim(),
                      notes: recvSupplierNotes.trim(),
                    });
                    if (!created?.success || !created?.id) {
                      setRecvMsg(created?.error || "Could not save the supplier.");
                      return;
                    }
                    supplierId = Number(created.id);
                    setRecvSupplier(String(supplierId));
                    setRecvName("");
                    setRecvPhone("");
                    setRecvSupplierNotes("");
                    qc.invalidateQueries({ queryKey: ["suppliers"] });
                  }
                  const lines = recvLines.length
                    ? recvLines.map((line) => ({
                        product_id: line.product_id,
                        quantity: line.quantity,
                        unit_cost: line.unit_cost,
                      }))
                    : [{
                        product_id: Number(recvId),
                        quantity: qty,
                        unit_cost: recvCost.trim() === "" ? null : Number(recvCost),
                      }];
                  if (!recvTokenRef.current) {
                    recvTokenRef.current =
                      typeof crypto !== "undefined" && crypto.randomUUID
                        ? crypto.randomUUID()
                        : `web-recv-${supplierId}`;
                  }
                  const res = await POST<any>("/stock-receipts", {
                    supplier_id: supplierId,
                    notes: recvNotes.trim(),
                    reference: recvNotes.trim(),
                    client_token: recvTokenRef.current,
                    lines,
                  });
                  if (!res?.success) {
                    setRecvMsg(res?.error || "Could not receive that delivery.");
                    return;
                  }
                  recvTokenRef.current = "";
                  setRecvMsg(
                    res.duplicate
                      ? `${res.receipt_number || "Delivery"} was already saved. Stock was not added again.`
                      : `${res.receipt_number || "Delivery"} saved${res.supplier_name ? ` from ${res.supplier_name}` : ""}. Total ${res.grand_total ?? ""}.`,
                  );
                  setRecvPin("");
                  setRecvLines([]);
                  await qc.invalidateQueries({ queryKey: ["products"] });
                  await qc.invalidateQueries({ queryKey: ["stock-receipts"] });
                  const fresh = await GET<StockReceipt[]>("/stock-receipts");
                  const opened = (Array.isArray(fresh) ? fresh : []).find(
                    (row) => Number(row.product_id) === Number(recvId),
                  );
                  if (opened) setReceipt(opened);
                } finally {
                  setRecvBusy(false);
                }
              }}
            >
              {recvBusy ? "Saving delivery…" : "Save supplier delivery"}
            </Button>
            {recvMsg ? <div className="text-sm text-text2">{recvMsg}</div> : null}
          </div>
        </Card>
      ) : null}
      <PageHeader
        eyebrow="Operations"
        title="Inventory"
        icon={<Package className="h-4 w-4" />}
        description={showStockValue
          ? `${products.length} SKUs · ${KES(totalValue, currency)} stock value${lowCount ? ` · ${lowCount} low` : ""}`
          : `${products.length} SKUs${lowCount ? ` · ${lowCount} low` : ""}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              onClick={() => setShowAdd(true)}
              className="min-h-[44px]"
            >
              Add product
            </Button>
            <Button
              variant="secondary"
              disabled={exporting}
              onClick={() => exportInv("csv")}
              className="min-h-[44px]"
            >
              <Download className="h-4 w-4" /> CSV
            </Button>
            <Button
              variant="secondary"
              disabled={exporting}
              onClick={() => exportInv("xlsx")}
              className="min-h-[44px]"
            >
              <Download className="h-4 w-4" /> Excel
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                qc.invalidateQueries({ queryKey: ["products"] });
                qc.invalidateQueries({ queryKey: ["stock-receipts"] });
              }}
              className="min-h-[44px]"
            >
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </div>
        }
      />

      {canReceive && !canAdjust ? (
        <Card className="mb-3">
          <form
            className="space-y-3 p-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              const res = await POST<any>("/stock-adjustment-requests", {
                product_id: Number(data.get("product_id")),
                requested_qty: Number(data.get("requested_qty")),
                reason: String(data.get("reason") || ""),
              });
              setRecvMsg(res?.error || `${res?.request_number || "Request"} sent. Stock was not changed.`);
              if (res?.success) {
                e.currentTarget.reset();
                qc.invalidateQueries({ queryKey: ["adjustment-requests"] });
              }
            }}
          >
            <div className="text-sm font-extrabold text-text">Ask for a stock adjustment</div>
            <div className="text-xs text-text2">This sends a request. It does not change stock.</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <select name="product_id" aria-label="Product to adjust" className="h-11 rounded-xl border border-border bg-panel px-3 text-sm">
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name} (stock {p.stock})</option>
                ))}
              </select>
              <Input name="requested_qty" aria-label="Target quantity" type="number" min={0} step={adjustStep} defaultValue="0" className="h-11" />
              <Input name="reason" aria-label="Adjustment reason" placeholder="Reason" className="h-11" required />
            </div>
            <Button type="submit">Send request</Button>
          </form>
        </Card>
      ) : null}
      {canAdjust ? (
        <Card className="mb-3">
          <div className="p-4 space-y-2">
            <div className="text-sm font-extrabold text-text">Pending adjustment requests</div>
            {user?.role === "superadmin" ? (
              <div className="text-xs text-text2">Signed in as Super Admin. A reduction does not ask for the PIN again.</div>
            ) : (
            <Input
              type="password"
              aria-label="Super-Admin PIN for this approval"
              placeholder="Super-Admin PIN for a reduction"
              value={reviewPin}
              onChange={(e) => setReviewPin(e.target.value)}
              className="h-11 max-w-xs"
            />
            )}
            {(requestsQ.data || []).length === 0 ? (
              <div className="text-sm text-text2">No pending requests.</div>
            ) : (requestsQ.data || []).map((row) => (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>
                  {row.request_number} · {row.product_name} · {row.current_stock} → {row.requested_qty}
                  <span className="text-text2"> · {row.reason}</span>
                </span>
                <span className="flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={async () => {
                      await POST(`/stock-adjustment-requests/${row.id}/review`, { decision: "rejected" });
                      qc.invalidateQueries({ queryKey: ["adjustment-requests"] });
                    }}
                  >Reject</Button>
                  <Button
                    onClick={async () => {
                      const res = await POST<any>(`/stock-adjustment-requests/${row.id}/review`, {
                        decision: "approved",
                        pin: reviewPin,
                      });
                      if (res?.error) setRecvMsg(res.error);
                      else {
                        setRecvMsg("Approved. Stock was updated once.");
                        setReviewPin("");
                      }
                      qc.invalidateQueries({ queryKey: ["adjustment-requests", "products"] });
                    }}
                  >Approve</Button>
                </span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
          <Input
            placeholder="Search by product name…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
            className="pl-8 min-h-[44px]"
          />
        </div>
        <Button type="button" variant="secondary" className="min-h-[44px]" onClick={() => setQ("")}>Clear</Button>
        <Button type="button" variant="secondary" className="min-h-[44px]" onClick={() => document.querySelector<HTMLInputElement>('input[placeholder="Search by product name…"]')?.focus()}>Search</Button>
      </div>
      <Card className="overflow-hidden">
        {productsQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading inventory…</div>
        ) : (
          <>
            {q.trim() && list.length === 0 ? (
              <div className="px-4 py-6 text-sm text-text2">No products match that name. Clear the search to see every product.</div>
            ) : null}
            <Table
              head={[
                "Photo",
                sortLabel("name", "Name"),
                "SKU",
                sortLabel("category", "Category"),
                sortLabel("price", "Price"),
                ...(seeCost ? ["Cost"] : []),
                sortLabel("stock", "Stock"),
                "Unit",
                ...(canRemove ? [""] : []),
              ]}
            >
              {pageRows.map((p) => {
                const stock = Number(p.stock) || 0;
                const oos = stock === 0;
                const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
                return (
                  <tr key={p.id}>
                    <td className="px-4 py-2.5">
                      <button
                        type="button"
                        className="rounded-xl focus-visible:ring-2 focus-visible:ring-gold/70"
                        aria-label={p.image_path ? `Change photograph for ${p.name}` : `Add photograph for ${p.name}`}
                        onClick={() => { setProductDetail(p); loadEdit(p); }}
                      >
                        <ProductPhoto src={p.image_path} size="sm" />
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-text font-medium">
                      <button
                        type="button"
                        className="font-semibold text-gold hover:underline"
                        onClick={() => { setProductDetail(p); loadEdit(p); }}
                      >
                        {p.name}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.sku || "—"}</td>
                    <td className="px-4 py-2.5 text-text2">{p.category || "General"}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                      {KES(p.price, currency)}
                    </td>
                    {seeCost ? (
                      <td className="px-4 py-2.5 tabular-nums text-text2">
                        {KES(p.cost_price ?? 0, currency)}
                      </td>
                    ) : null}
                    <td className="px-4 py-2.5 tabular-nums">
                      <Badge tone={oos ? "err" : low ? "warn" : "muted"}>{stock}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-text2">{p.unit || "pcs"}</td>
                    {canRemove ? (
                      <td className="px-4 py-2.5">
                        <Button variant="danger" size="sm" onClick={() => archiveProduct(p)}>
                          Remove
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </Table>
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-border text-xs text-text2">
              <span>
                Page {page + 1} / {pageCount} · {list.length} shown
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={page <= 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>

      {showAdd ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setShowAdd(false)}>
          <div className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <Card className="p-5">
              <div className="mb-3 text-lg font-extrabold text-text">Add product</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="text-xs text-text2 sm:col-span-2">Name
                  <Input className="mt-1 h-11" value={newProduct.name} onChange={(e) => setNewProduct({ ...newProduct, name: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Selling price
                  <Input className="mt-1 h-11" type="number" min={0} value={newProduct.price} onChange={(e) => setNewProduct({ ...newProduct, price: e.target.value })} />
                </label>
                {seeCost ? (
                  <label className="text-xs text-text2">Cost
                    <Input className="mt-1 h-11" type="number" min={0} value={newProduct.cost_price} onChange={(e) => setNewProduct({ ...newProduct, cost_price: e.target.value })} />
                  </label>
                ) : null}
                <label className="text-xs text-text2">Opening stock
                  <Input className="mt-1 h-11" type="number" min={0} value={newProduct.stock} onChange={(e) => setNewProduct({ ...newProduct, stock: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Unit
                  <Input className="mt-1 h-11" value={newProduct.unit} onChange={(e) => setNewProduct({ ...newProduct, unit: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Category
                  <Input className="mt-1 h-11" value={newProduct.category} onChange={(e) => setNewProduct({ ...newProduct, category: e.target.value })} />
                </label>
                <label className="text-xs text-text2">SKU
                  <Input className="mt-1 h-11" value={newProduct.sku} onChange={(e) => setNewProduct({ ...newProduct, sku: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Barcode
                  <Input aria-label="New product barcode" className="mt-1 h-11" value={newProduct.barcode} onChange={(e) => setNewProduct({ ...newProduct, barcode: e.target.value })} />
                </label>
              </div>
              <div className="mt-3">
                <ProductPhoto
                  preview={newPhotoUrl}
                  size="lg"
                  onFile={(file) => {
                    setNewPhoto(file);
                    setNewPhotoUrl(URL.createObjectURL(file));
                  }}
                  onRemove={newPhotoUrl ? () => { setNewPhoto(null); setNewPhotoUrl(""); } : undefined}
                />
                <div className="mt-2 text-xs text-text2">Click the camera to add a JPEG, PNG, or WebP photograph.</div>
              </div>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setShowAdd(false)}>Cancel</Button>
                <Button
                  variant="primary"
                  disabled={savingProduct}
                  onClick={async () => {
                    if (!newProduct.name.trim()) {
                      toast.error("Enter the product name.");
                      return;
                    }
                    setSavingProduct(true);
                    try {
                      const created = await POST<{ success?: boolean; id?: number; error?: string }>("/products", {
                        name: newProduct.name.trim(),
                        sku: newProduct.sku.trim(),
                        category: newProduct.category.trim(),
                        price: Number(newProduct.price || 0),
                        cost_price: Number(newProduct.cost_price || 0),
                        stock: Number(newProduct.stock || 0),
                        unit: newProduct.unit.trim() || "pcs",
                        barcode: newProduct.barcode.trim(),
                      });
                      if (!created || created.error || !created.id) {
                        toast.error(created?.error || "The product was not saved.");
                        return;
                      }
                      if (newPhoto) {
                        const body = new FormData();
                        body.append("image", newPhoto);
                        const response = await fetch(`/api/products/${created.id}/image`, {
                          method: "POST",
                          headers: { Authorization: `Bearer ${getToken()}` },
                          body,
                        });
                        const data = await response.json().catch(() => ({}));
                        if (!response.ok || data.error) {
                          toast.error(data.error || "The product was saved, but the photograph was not.");
                        }
                      }
                      setShowAdd(false);
                      setNewProduct({ name: "", sku: "", category: "", price: "", cost_price: "", stock: "0", unit: "pcs", barcode: "" });
                      setNewPhoto(null);
                      setNewPhotoUrl("");
                      qc.invalidateQueries({ queryKey: ["products"] });
                      toast.success("Product saved.");
                    } finally {
                      setSavingProduct(false);
                    }
                  }}
                >
                  {savingProduct ? "Saving…" : "Save product"}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}

      {productDetail ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
          onClick={() => setProductDetail(null)}
        >
          <div className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <Card className="overflow-hidden">
              <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-text2">Product</div>
                  <div className="mt-1 text-lg font-extrabold text-text">{productDetail.name}</div>
                </div>
                <Button variant="ghost" onClick={() => setProductDetail(null)}>
                  Close
                </Button>
              </div>
              <div className="px-5 pt-4">
                <ProductPhoto
                  src={productDetail.image_path}
                  size="lg"
                  onFile={async (file) => {
                    const body = new FormData();
                    body.append("image", file);
                    const response = await fetch(`/api/products/${productDetail.id}/image`, {
                      method: "POST",
                      headers: { Authorization: `Bearer ${getToken()}` },
                      body,
                    });
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.error) {
                      toast.error(data.error || "The photograph was not saved.");
                      return;
                    }
                    const stamped = `${data.image_path}?v=${Date.now()}`;
                    setProductDetail({ ...productDetail, image_path: stamped });
                    qc.invalidateQueries({ queryKey: ["products"] });
                    toast.success("Photograph saved.");
                  }}
                  onRemove={productDetail.image_path ? async () => {
                    const response = await fetch(`/api/products/${productDetail.id}/image`, {
                      method: "DELETE",
                      headers: { Authorization: `Bearer ${getToken()}` },
                    });
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.error) {
                      toast.error(data.error || "The photograph was not removed.");
                      return;
                    }
                    setProductDetail({ ...productDetail, image_path: "" });
                    qc.invalidateQueries({ queryKey: ["products"] });
                    toast.success("Photograph removed.");
                  } : undefined}
                />
              </div>
              <div className="space-y-3 px-5 py-4">
                <div className="text-xs text-text2">
                  On hand {Number(productDetail.stock || 0)} {productDetail.unit || "pcs"}.
                  Change the quantity under Adjust stock. It is not changed here.
                </div>
                {canEdit ? adjustFields : null}
                {canEdit ? (
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={saveEdit} disabled={editBusy}>
                      {editBusy ? "Saving…" : "Save product details"}
                    </Button>
                    {canRemove ? (
                      <Button variant="danger" onClick={() => archiveProduct(productDetail)}>Remove product</Button>
                    ) : null}
                  </div>
                ) : null}
                {editMsg ? <div className="text-sm text-text2">{editMsg}</div> : null}
              </div>
            </Card>
          </div>
        </div>
      ) : null}

      {receipt ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
          onClick={() => setReceipt(null)}
        >
          <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
          <Card className="overflow-hidden">
            {(() => {
              const product = products.find((p) => p.id === receipt.product_id);
              const name = receipt.product_name || product?.name || "Product";
              const sku = receipt.sku || product?.sku || "—";
              const category = receipt.category || product?.category || "General";
              const barcode = receipt.barcode || "—";
              const unit = receipt.unit || product?.unit || "pcs";
              const price = receipt.price ?? product?.price;
              const cost = receipt.cost_price ?? product?.cost_price;
              const onHand = receipt.current_stock ?? product?.stock;
              const minStock = receipt.min_stock ?? product?.min_stock;
              return (
                <>
            <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-text2">
                  Product from this supplier receipt
                </div>
                <div className="mt-1 text-lg font-extrabold text-text">{name}</div>
                <div className="text-sm text-text2">
                  {category} · {sku} · {String(receipt.created_at || "").replace("T", " ").slice(0, 19)}
                </div>
              </div>
              <Button variant="ghost" onClick={() => setReceipt(null)}>
                Close
              </Button>
            </div>
            <div className="px-5 pt-4 text-xs font-semibold uppercase tracking-wide text-text2">
              Product
            </div>
            <div className="grid grid-cols-2 gap-3 px-5 py-3 text-sm">
              {[
                ["Name", name],
                ["Category", category],
                ["SKU", sku],
                ["Barcode", barcode],
                ["Selling price", price == null ? "—" : KES(Number(price), currency)],
                ["Cost", cost == null ? "—" : KES(Number(cost), currency)],
                ["Unit", unit],
                ["On hand now", onHand == null ? "—" : String(Number(onHand))],
                ["Low-stock alert", minStock == null ? "—" : String(Number(minStock))],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="text-xs text-text2">{label}</div>
                  <div className="mt-1 font-semibold text-text">{value}</div>
                </div>
              ))}
            </div>
            <div className="border-t border-border px-5 pt-4 text-xs font-semibold uppercase tracking-wide text-text2">
              This delivery
            </div>
            <div className="grid grid-cols-2 gap-3 px-5 py-3 text-sm">
              {[
                ["Supplier", receipt.supplier_name || "No supplier"],
                ["Phone", receipt.supplier_phone || "—"],
                ["Supplier note", receipt.supplier_notes || "—"],
                ["Quantity received", `+${Number(receipt.qty_change || 0)} ${unit}`],
                ["Stock before", String(Number(receipt.qty_before || 0))],
                ["Stock after", String(Number(receipt.qty_after || 0))],
                ["Received by", receipt.username || "—"],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="text-xs text-text2">{label}</div>
                  <div className="mt-1 font-semibold text-text">{value}</div>
                </div>
              ))}
            </div>
            {receipt.lines && receipt.lines.length ? (
              <div className="border-t border-border px-5 py-4 text-sm">
                <div className="text-xs font-semibold uppercase tracking-wide text-text2">
                  {receipt.receipt_number || "Products on this delivery"}
                </div>
                {receipt.lines.map((line, index) => (
                  <div key={`${line.product_name}-${index}`} className="mt-2 flex justify-between gap-3">
                    <span className="text-text">{line.product_name}</span>
                    <span className="tabular-nums text-text2">
                      {Number(line.quantity || 0)} × {Number(line.unit_cost || 0).toFixed(2)} = {Number(line.line_total || 0).toFixed(2)}
                    </span>
                  </div>
                ))}
                <div className="mt-3 font-extrabold text-text">
                  Grand total {Number(receipt.grand_total || 0).toFixed(2)}
                </div>
              </div>
            ) : null}
            <div className="border-t border-border px-5 py-4 text-sm">
              <div className="text-xs text-text2">Delivery note</div>
              <div className="mt-1 text-text">{receipt.reason || "—"}</div>
            </div>
                </>
              );
            })()}
          </Card>
          </div>
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between text-xs text-text2">
        <div>
          <span className="text-text font-semibold">{products.length}</span> products
          <span className="text-muted-fg mx-2">·</span>
          <span className="text-warn font-semibold">{lowCount}</span> low stock
        </div>
        {showStockValue ? (
          <div>
            Stock value:{" "}
            <span className="text-gold font-bold text-sm tabular-nums">
              {KES(totalValue, currency)}
            </span>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
