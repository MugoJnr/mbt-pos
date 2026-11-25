import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, RefreshCw, Package, Download } from "lucide-react";
import { ProductPhoto } from "@/components/product-photo";
import { CategoryField } from "@/components/category-field";
import { ShopCategories } from "@/components/shop-categories";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { DEL, GET, POST, PUT, getToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApiPost } from "@/lib/download";
import { ExportLockDialog } from "@/components/export-lock-dialog";
import { DeliveryActions } from "@/components/delivery-actions";
import { BusinessDateField, canPostBusinessDay } from "@/components/business-date-field";
import { KES, shopTodayISO, todayISO } from "@/lib/format";
import { parseQuantity } from "@/lib/quantity";
import {
  UNCATEGORISED,
  assignedCategory,
  catalogMatches,
  categoryMatches,
  sortInventory,
  stockBand,
  type InventorySort,
} from "@/lib/inventory-filters";
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
  allow_decimal_qty?: number | null;
  image_path?: string;
  is_active?: number;
  created_at?: string;
  updated_at?: string;
  cost_confirmed?: number;
  cost_health?: {
    primary?: string;
    badges?: { code: string; label: string; tone?: "err" | "warn" | "ok" | "muted" }[];
  };
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
  reference?: string;
  notes?: string;
  status?: string;
  supplier_id?: number;
  amount_paid?: number;
  outstanding?: number;
  payment_status?: string;
  reference_note?: string;
  due_date?: string;
  payments?: { payment_number?: string; method?: string; reference?: string; allocated?: number; amount?: number }[];
  grouped?: boolean;
  lines?: {
    product_id?: number;
    product_name?: string;
    quantity?: number;
    unit_cost?: number;
    line_total?: number;
    unit?: string;
    sku?: string;
    old_stock?: number;
    new_stock?: number;
    returned_qty?: number;
    rejected_qty?: number;
    ordered_qty?: number | null;
  }[];
  grn_text?: string;
};

function WorkPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-3 sm:p-6" onClick={onClose}>
      <div className="mx-auto w-full max-w-5xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="text-sm font-extrabold text-white">{title}</div>
          <Button variant="secondary" onClick={onClose}>Close</Button>
        </div>
        {children}
      </div>
    </div>
  );
}

function SuppliersPanel({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient();
  const suppliersQ = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => GET<{ id: number; name?: string; phone?: string; notes?: string; error?: string }[]>("/suppliers"),
  });
  const rows = Array.isArray(suppliersQ.data) ? suppliersQ.data : [];
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function addSupplier() {
    setMsg("");
    setBusy(true);
    try {
      const created = await POST<{ id?: number; error?: string }>("/suppliers", { name, phone, notes });
      if (!created || created.error || !created.id) {
        setMsg(created?.error || "The supplier was not saved.");
        return;
      }
      setName("");
      setPhone("");
      setNotes("");
      setMsg("Supplier saved. New receipts can use this supplier.");
      await qc.invalidateQueries({ queryKey: ["suppliers"] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="space-y-3 p-4">
        <div className="text-sm font-extrabold text-text">Suppliers</div>
        <div className="text-xs text-text2">The same suppliers used on stock receipts and batches.</div>
        {canManage ? (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
            <Input aria-label="Supplier name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} className="h-11" />
            <Input aria-label="Supplier phone" placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} className="h-11" />
            <Input aria-label="Supplier notes" placeholder="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="h-11" />
            <Button disabled={busy || !name.trim()} onClick={() => void addSupplier()}>{busy ? "Saving…" : "Add supplier"}</Button>
          </div>
        ) : (
          <div className="text-xs text-text2">You can view suppliers. Adding or editing a supplier needs supplier management.</div>
        )}
        {msg ? <div className="text-sm text-text2">{msg}</div> : null}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-text2">
              <tr>
                <th className="px-2 py-2">Name</th>
                <th className="px-2 py-2">Phone</th>
                <th className="px-2 py-2">Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-border">
                  <td className="px-2 py-2 font-semibold text-text">{row.name || "Supplier"}</td>
                  <td className="px-2 py-2 text-text2">{row.phone || "—"}</td>
                  <td className="px-2 py-2 text-text2">{row.notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length ? <div className="py-3 text-sm text-text2">No suppliers yet.</div> : null}
        </div>
      </div>
    </Card>
  );
}

function Inventory() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const actions = Array.isArray(user?.effective_permissions) ? user.effective_permissions.map(String) : null;
  const canAdjust = actions ? actions.includes("inventory.adjust_stock") : role === "superadmin";
  const canEdit = actions ? actions.includes("inventory.edit_info") : ["manager", "admin", "superadmin"].includes(role);
  const canCreate = actions ? actions.includes("inventory.create") : ["manager", "admin", "superadmin"].includes(role);
  const canCreateCategory = actions ? actions.includes("categories.create") : ["cashier", "manager", "admin", "superadmin"].includes(role);
  const canManageCategories = actions ? actions.includes("categories.manage") : role === "admin" || role === "superadmin";
  const canDeleteCategory = actions ? actions.includes("categories.delete") : role === "admin" || role === "superadmin";
  const canRemove = actions ? actions.includes("inventory.delete") : role === "admin" || role === "superadmin";
  const canReceive = actions
    ? actions.includes("inventory.receive")
    : ["manager", "admin", "superadmin"].includes(role);
  const canRestock = actions ? actions.includes("restock.view") : ["viewer", "manager", "admin", "superadmin"].includes(role);
  const canExport = actions ? actions.includes("reports.export") : ["manager", "admin", "superadmin"].includes(role);
  const canViewSuppliers = actions
    ? actions.includes("supplier.view") || actions.includes("supplier.manage")
    : ["viewer", "manager", "admin", "superadmin"].includes(role);
  const canManageSuppliers = actions ? actions.includes("supplier.manage") : role === "admin" || role === "superadmin";
  const canStocktake = role !== "viewer" && (actions ? actions.includes("inventory.view") : role !== "cashier");
  const canOpenRequests = canAdjust || (canReceive && role !== "viewer");
  const [panel, setPanel] = useState<null | "categories" | "edit" | "receive" | "batches" | "stocktake" | "adjust" | "requests" | "suppliers">(null);
  const [refreshing, setRefreshing] = useState(false);
  const canBatchPrice = actions
    ? actions.includes("inventory.batch_price")
    : ["manager", "admin", "superadmin"].includes(role);
  const [adjId, setAdjId] = useState("");
  const [adjDir, setAdjDir] = useState("add");
  const [adjQty, setAdjQty] = useState("1");
  const [adjReason, setAdjReason] = useState("Correction");
  const [adjDate, setAdjDate] = useState(shopTodayISO);
  const [adjDateConfirmed, setAdjDateConfirmed] = useState(false);
  const [adjBackdate, setAdjBackdate] = useState("");
  const [adjMsg, setAdjMsg] = useState("");
  const [adjPin, setAdjPin] = useState("");
  const [adjPinUser, setAdjPinUser] = useState("");
  const [reviewPin, setReviewPin] = useState("");
  const seeCost = actions
    ? actions.includes("inventory.view_cost")
    : role !== "cashier" && role !== "viewer";
  const showStockValue = ["manager", "admin", "superadmin"].includes(role);
  const [recvId, setRecvId] = useState("");
  const [recvQty, setRecvQty] = useState("1");
  const [recvSupplier, setRecvSupplier] = useState("");
  const [recvName, setRecvName] = useState("");
  const [recvPhone, setRecvPhone] = useState("");
  const [recvSupplierNotes, setRecvSupplierNotes] = useState("");
  const [recvNotes, setRecvNotes] = useState("");
  const [recvReference, setRecvReference] = useState("");
  const [recvSearch, setRecvSearch] = useState("");
  const [recvPin, setRecvPin] = useState("");
  const [recvMsg, setRecvMsg] = useState("");
  const [recvBusy, setRecvBusy] = useState(false);
  const recvTokenRef = useRef("");
  const [recvLines, setRecvLines] = useState<
    { product_id: number; name: string; sku?: string; unit?: string; quantity: number | string; unit_cost: number | null; sell_price?: number | null; rejected_qty?: number; ordered_qty?: number | null; explicit_zero?: boolean; allow_excess?: boolean }[]
  >([]);
  const [batchSearch, setBatchSearch] = useState("");
  const batchesQ = useQuery({
    queryKey: ["batches", batchSearch],
    queryFn: () => GET<any>("/batches", batchSearch ? { q: batchSearch } : undefined),
  });
  const [recvCost, setRecvCost] = useState("");
  const [recvSell, setRecvSell] = useState("");
  const [recvRejected, setRecvRejected] = useState("");
  const [recvOrdered, setRecvOrdered] = useState("");
  const [recvFree, setRecvFree] = useState(false);
  const [recvExcess, setRecvExcess] = useState(false);
  const [recvExtra, setRecvExtra] = useState("");
  const [recvPaid, setRecvPaid] = useState("");
  const [recvPayMethod, setRecvPayMethod] = useState("cash");
  const [recvPayRef, setRecvPayRef] = useState("");
  const [recvDue, setRecvDue] = useState("");
  const [recvDate, setRecvDate] = useState(shopTodayISO);
  const [recvDateConfirmed, setRecvDateConfirmed] = useState(false);
  const [recvBackdateReason, setRecvBackdateReason] = useState("");
  const [productDetail, setProductDetail] = useState<Product | null>(null);
  const historyQ = useQuery({
    queryKey: ["product-history", productDetail?.id],
    queryFn: () => GET<any>(`/products/${productDetail?.id}/history`),
    enabled: Boolean(productDetail?.id),
  });
  const [editId, setEditId] = useState("");
  const [editForm, setEditForm] = useState({
    name: "", sku: "", barcode: "", category: "", price: "", cost_price: "",
    unit: "pcs", decimal_qty: "", min_stock: "5", is_active: "1",
  });
  const [editMsg, setEditMsg] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [stocktakeName, setStocktakeName] = useState("");
  const [stocktakeId, setStocktakeId] = useState<number | null>(null);
  const [stocktakeProduct, setStocktakeProduct] = useState("");
  const [stocktakeQty, setStocktakeQty] = useState("");
  const [stocktakeDate, setStocktakeDate] = useState(shopTodayISO);
  const [stocktakeBackdate, setStocktakeBackdate] = useState("");
  const [stocktakeMsg, setStocktakeMsg] = useState("");
  const [newProduct, setNewProduct] = useState({
    name: "", sku: "", category: "", price: "", cost_price: "", stock: "0", unit: "pcs", decimal_qty: "", barcode: "",
  });
  const [newPhoto, setNewPhoto] = useState<File | null>(null);
  const [newPhotoUrl, setNewPhotoUrl] = useState("");
  const [savingProduct, setSavingProduct] = useState(false);
  const [q, setQ] = useState("");
  const [costFilter, setCostFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [sortMode, setSortMode] = useState<InventorySort>("name_asc");
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [invLock, setInvLock] = useState<"xlsx" | "csv" | null>(null);
  const [invLockError, setInvLockError] = useState("");
  const [receipt, setReceipt] = useState<StockReceipt | null>(null);
  const pageSize = 40;

  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const categoriesQ = useQuery({
    queryKey: ["categories"],
    queryFn: () => GET<{ id: number; name?: string }[]>("/categories"),
  });
  const stocktakesQ = useQuery({
    queryKey: ["stocktakes"],
    queryFn: () => GET<{ stocktakes?: { id: number; name?: string; status?: string; created_at?: string }[] }>("/stocktakes"),
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
  const receiptsQ = useQuery({
    queryKey: ["stock-receipts"],
    queryFn: () => GET<StockReceipt[]>("/stock-receipts"),
    enabled: canReceive,
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";
  const adjustStep = wheelStep(settingsQ.data, "wheel_stock_adjust");
  const qtyStep = wheelStep(settingsQ.data, "wheel_dashboard_qty");
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const suppliers = Array.isArray(suppliersQ.data) ? suppliersQ.data : [];
  const selectedProduct = products.find((p) => String(p.id) === adjId);
  const categoryOptions = useMemo(() => {
    const names = new Map<string, string>();
    for (const row of categoriesQ.data || []) {
      const label = assignedCategory({ category: row.name });
      if (label) names.set(label.toLowerCase(), label);
    }
    for (const product of products) {
      const label = assignedCategory(product);
      if (label && !names.has(label.toLowerCase())) names.set(label.toLowerCase(), label);
    }
    return [...names.values()].sort((a, b) => a.localeCompare(b));
  }, [categoriesQ.data, products]);

  const list = useMemo(() => {
    const filtered = products.filter((p) => {
      if (!catalogMatches(q, p)) return false;
      if (statusFilter !== "all" && stockBand(p) !== statusFilter) return false;
      if (!categoryMatches(p, categoryFilter)) return false;
      const codes = new Set((p.cost_health?.badges || []).map((badge) => badge.code));
      if (!costFilter) return true;
      if (costFilter === "zero_or_invalid") {
        return codes.has("explicit_zero") || codes.has("invalid_price") || codes.has("zero_review");
      }
      if (costFilter === "inconsistent") {
        return codes.has("inconsistent") || codes.has("zero_review") || codes.has("stock_without_cost");
      }
      return codes.has(costFilter);
    });
    return sortInventory(filtered, sortMode);
  }, [products, q, statusFilter, categoryFilter, sortMode, costFilter]);

  const pageCount = Math.max(1, Math.ceil(list.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = list.slice(safePage * pageSize, safePage * pageSize + pageSize);
  useEffect(() => {
    if (page !== safePage) setPage(safePage);
  }, [page, safePage]);

  const valuationQ = useQuery({
    queryKey: ["inventory-valuation", productsQ.dataUpdatedAt],
    queryFn: () => GET<{ value?: number; quantity?: number; costing_incomplete?: boolean; products_needing_review?: number }>("/inventory-valuation"),
    enabled: seeCost,
  });
  const totalValue = seeCost && valuationQ.data && typeof valuationQ.data.value === "number"
    ? valuationQ.data.value
    : null;
  const lowCount = products.filter((p) => stockBand(p) === "low").length;

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
      decimal_qty: p.allow_decimal_qty == null || p.allow_decimal_qty === undefined ? "" : String(p.allow_decimal_qty),
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
      allow_decimal_qty: editForm.decimal_qty === "" ? null : Number(editForm.decimal_qty),
      min_stock: Number(editForm.min_stock || 0),
    };
    if (canRemove) body.is_active = editForm.is_active === "0" ? 0 : 1;
    if (seeCost) {
      const rawCost = editForm.cost_price.trim();
      if (!rawCost) {
        body.cost_price = null;
      } else {
        const cost = Number(rawCost);
        if (!Number.isFinite(cost) || cost < 0) {
          setEditMsg("Enter a buying price, or leave it blank when the price is unknown. Type 0 only for free stock.");
          return;
        }
        body.cost_price = cost;
        if (cost === 0) body.explicit_zero = true;
      }
    }
    setEditBusy(true);
    try {
      const res = await PUT<{ success?: boolean; error?: string; pending_approval?: boolean; message?: string }>(`/products/${editId}`, body);
      if (!res?.success) {
        setEditMsg(res?.error || "The product was not saved.");
        return;
      }
      if (res.pending_approval) {
        setEditMsg(res.message || "Waiting for an administrator. The live product was not changed.");
        qc.invalidateQueries({ queryKey: ["products"] });
        return;
      }
      setEditMsg(res.message || "Product details saved. Stock quantity was not changed.");
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
          <span className="mt-1 block text-[11px] text-text2">Leave blank if the buying price is unknown. Type 0 only for free stock.</span>
        </label>
      ) : null}
      <label className="text-xs font-semibold text-text2">SKU
        <Input aria-label="SKU" className="mt-1 h-11" value={editForm.sku} onChange={(e) => setEditForm({ ...editForm, sku: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Barcode
        <Input aria-label="Barcode" className="mt-1 h-11" value={editForm.barcode} onChange={(e) => setEditForm({ ...editForm, barcode: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Category
        <CategoryField
          value={editForm.category}
          canCreate={canCreateCategory}
          onChange={(category) => setEditForm({ ...editForm, category })}
        />
      </label>
      <label className="text-xs font-semibold text-text2">Unit
        <Input aria-label="Unit" className="mt-1 h-11" value={editForm.unit} onChange={(e) => setEditForm({ ...editForm, unit: e.target.value })} />
      </label>
      <label className="text-xs font-semibold text-text2">Decimal quantities
        <select aria-label="Decimal quantities" className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text" value={editForm.decimal_qty} onChange={(e) => setEditForm({ ...editForm, decimal_qty: e.target.value })}>
          <option value="">Follow the unit</option>
          <option value="1">Allow decimal quantities</option>
          <option value="0">Whole quantities only</option>
        </select>
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
    setSortMode((current) => {
      if (key === "name") return current === "name_asc" ? "name_desc" : "name_asc";
      if (key === "stock") return current === "stock_asc" ? "stock_desc" : "stock_asc";
      if (key === "price") return current === "price_asc" ? "price_desc" : "price_asc";
      return current === "category_asc" ? "category_desc" : "category_asc";
    });
    setPage(0);
  }

  function sortActive(key: SortKey) {
    return sortMode.startsWith(key);
  }

  function sortArrow(key: SortKey) {
    if (!sortActive(key)) return "";
    return sortMode.endsWith("desc") ? "↓" : "↑";
  }

  async function exportInv(format: "xlsx" | "csv", password: string) {
    try {
      setExporting(true);
      setInvLockError("");
      const ext = format === "csv" ? "zip" : format;
      await downloadApiPost(
        "/reports/export",
        { format, inventory: "1", password, confirm: password },
        `MBT_Inventory_${todayISO()}.${ext}`,
      );
      setInvLock(null);
      toast.success(format === "csv" ? "Encrypted ZIP downloaded" : "Encrypted Excel downloaded");
    } catch (e: any) {
      setInvLockError(e?.message || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function exportVisible() {
    const headers = ["Name", "SKU", "Barcode", "Category", "Selling price", ...(seeCost ? ["Buying price"] : []), "Stock", "Unit", "Reorder level"];
    const esc = (value: unknown) => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const body = list.map((p) => [
      p.name,
      p.sku || "",
      p.barcode || "",
      p.category || "Uncategorised",
      p.price,
      ...(seeCost ? [p.cost_price ?? ""] : []),
      p.stock ?? 0,
      p.unit || "pcs",
      p.min_stock ?? "",
    ]);
    const xml = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="Inventory"><Table>
<Row>${headers.map((cell) => `<Cell><Data ss:Type="String">${esc(cell)}</Data></Cell>`).join("")}</Row>
${body.map((row) => `<Row>${row.map((cell) => `<Cell><Data ss:Type="${typeof cell === "number" ? "Number" : "String"}">${esc(cell)}</Data></Cell>`).join("")}</Row>`).join("")}
</Table></Worksheet></Workbook>`;
    const blob = new Blob([xml], { type: "application/vnd.ms-excel" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `MBT_Inventory_${todayISO()}.xls`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success(`${list.length} product${list.length === 1 ? "" : "s"} exported.`);
  }

  async function refreshInventory() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["products"] }),
        qc.invalidateQueries({ queryKey: ["categories"] }),
        qc.invalidateQueries({ queryKey: ["batches"] }),
        qc.invalidateQueries({ queryKey: ["suppliers"] }),
        qc.invalidateQueries({ queryKey: ["stocktakes"] }),
        qc.invalidateQueries({ queryKey: ["adjustment-requests"] }),
        qc.invalidateQueries({ queryKey: ["stock-receipts"] }),
      ]);
    } finally {
      setRefreshing(false);
    }
  }

  const sortLabel = (key: SortKey, label: string) => (
    <button type="button" onClick={() => toggleSort(key)} className="hover:text-gold">
      {label} {sortArrow(key)}
    </button>
  );

  return (
    <AppShell title="Inventory">
      {panel === "categories" && (canManageCategories || canCreateCategory) ? (
        <WorkPanel title="Shop categories" onClose={() => setPanel(null)}>
        <ShopCategories
          canCreate={canCreateCategory}
          canManage={canManageCategories}
          canDelete={canDeleteCategory}
        />
        </WorkPanel>
      ) : null}
      <ExportLockDialog
        open={invLock != null}
        kind={invLock === "csv" ? "CSV" : "Excel workbook"}
        busy={exporting}
        error={invLockError}
        onCancel={() => {
          if (!exporting) setInvLock(null);
        }}
        onConfirm={(password) => {
          if (invLock) void exportInv(invLock, password);
        }}
      />
      {panel === "edit" && canEdit ? (
        <WorkPanel title="Edit product" onClose={() => setPanel(null)}>
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
        </WorkPanel>
      ) : null}
      {panel === "adjust" && canAdjust ? (
        <WorkPanel title="Adjust stock" onClose={() => setPanel(null)}>
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
              <>
              <label className="text-xs font-semibold text-text2">
                Super Admin username
                <Input
                  aria-label="Super Admin username"
                  value={adjPinUser}
                  onChange={(e) => setAdjPinUser(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                That Super Admin's PIN
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
              </>
              )}
              <BusinessDateField label="Adjustment date" value={adjDate} onChange={setAdjDate} confirmed={adjDateConfirmed} onConfirm={setAdjDateConfirmed} reason={adjBackdate} onReason={setAdjBackdate} />
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
                if (!adjId) {
                  setAdjMsg("Select a product.");
                  return;
                }
                const parsedAdj = parseQuantity(adjQty, selectedProduct?.unit, { allowZero: adjDir === "set" });
                if ("error" in parsedAdj) {
                  setAdjMsg(parsedAdj.error.includes("whole units")
                    ? `${selectedProduct?.name || "This product"} is sold in whole units.`
                    : parsedAdj.error);
                  return;
                }
                const qty = parsedAdj.quantity;
                if (qty < 0 || (adjDir !== "set" && qty === 0)) {
                  setAdjMsg("Enter a quantity greater than zero.");
                  return;
                }
                if (user?.role !== "superadmin" && !adjPin.trim()) {
                  setAdjMsg("Super-Admin PIN is required.");
                  return;
                }
                if (adjDate < shopTodayISO() && (adjBackdate.trim().length < 3 || adjBackdate.trim() === "Other")) {
                  setAdjMsg("Choose a reason for this past date. If you choose Other, write what happened.");
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
                  pin_username: adjPinUser,
                  business_date: adjDate,
                  backdate_reason: adjBackdate.trim(),
                  client_token: `adj-${adjId}-${adjDate}-${newQty}`,
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
        </WorkPanel>
      ) : null}
      {panel === "batches" ? (
        <WorkPanel title="Batches" onClose={() => setPanel(null)}>
        <Card className="mb-3">
        <div className="p-4 space-y-3">
          <div className="text-sm font-extrabold text-text">Batches</div>
          <div className="text-xs text-text2">Every delivery batch, including finished batches. Open a product history row to change a selling price.</div>
          <Input
            aria-label="Search batches"
            value={batchSearch}
            placeholder="Search product, batch, or supplier"
            onChange={(e) => setBatchSearch(e.target.value)}
            className="h-11 max-w-md"
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-text2">
                <tr>
                  <th className="px-2 py-2">Batch</th>
                  <th className="px-2 py-2">Product</th>
                  <th className="px-2 py-2">Supplier</th>
                  <th className="px-2 py-2">Left</th>
                  <th className="px-2 py-2">Selling</th>
                  <th className="px-2 py-2">Price</th>
                  <th className="px-2 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {(batchesQ.data?.batches || []).map((batch: any) => (
                  <tr key={batch.id} className="border-t border-border">
                    <td className="px-2 py-2">{batch.batch_ref}</td>
                    <td className="px-2 py-2">{batch.product_name}</td>
                    <td className="px-2 py-2">{batch.supplier_name || "—"}</td>
                    <td className="px-2 py-2 tabular-nums">{batch.remaining_qty}</td>
                    <td className="px-2 py-2 tabular-nums">{batch.effective_sell_price == null ? "—" : KES(batch.effective_sell_price)}</td>
                    <td className="px-2 py-2">{batch.price_mode === "custom" ? "Custom" : "Normal"}</td>
                    <td className="px-2 py-2">{batch.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {batchesQ.data && !(batchesQ.data.batches || []).length ? (
              <div className="py-3 text-sm text-text2">No batches match that search.</div>
            ) : null}
          </div>
        </div>
      </Card>
        </WorkPanel>
      ) : null}
      {panel === "receive" && canReceive ? (
        <WorkPanel title="Receive stock" onClose={() => setPanel(null)}>
        <Card className="mb-3">
          <div className="p-4 space-y-3">
            <div className="text-sm font-extrabold text-text">Receive stock</div>
            <div className="text-xs text-text2">
              Add every product on this delivery, then save once. No extra PIN. One receipt covers all of the lines.
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-text2 md:col-span-2">
                Search products
                <Input
                  aria-label="Search products to receive"
                  value={recvSearch}
                  onChange={(e) => setRecvSearch(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Name or SKU"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                Product
                <select
                  aria-label="Receive product"
                  value={recvId}
                  onMouseDown={() => {
                    const chosen = products.find((p) => String(p.id) === recvId);
                    const typed = recvSearch.trim().toLowerCase();
                    const name = String(chosen?.name || "").trim().toLowerCase();
                    const sku = String(chosen?.sku || "").trim().toLowerCase();
                    if (!typed || typed === name || typed === sku) setRecvSearch("");
                  }}
                  onChange={(e) => setRecvId(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
                >
                  <option value="">Select a product</option>
                  {products.filter((p) => {
                    const needle = recvSearch.trim().toLowerCase();
                    if (!needle) return true;
                    return `${p.name || ""} ${p.sku || ""}`.toLowerCase().includes(needle);
                  }).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.sku || "no SKU"} · {p.unit || "pcs"} · stock {p.stock}
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
                  step="any"
                  value={recvQty}
                  onChange={(e) => setRecvQty(e.target.value)}
                  className="mt-1 h-11"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                Ordered quantity
                <Input
                  aria-label="Ordered quantity"
                  type="number"
                  min={0}
                  step="any"
                  value={recvOrdered}
                  onChange={(e) => setRecvOrdered(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Blank if not tracking an order"
                />
              </label>
              <label className="text-xs font-semibold text-text2">
                Rejected quantity
                <Input
                  aria-label="Rejected quantity"
                  type="number"
                  min={0}
                  step="any"
                  value={recvRejected}
                  onChange={(e) => setRecvRejected(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Damaged or refused. Not added to stock"
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
                Invoice or delivery reference
                <Input
                  aria-label="Delivery reference"
                  value={recvReference}
                  onChange={(e) => setRecvReference(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Supplier invoice number"
                />
              </label>
              <label className="text-xs font-semibold text-text2 md:col-span-2">
                Notes
                <Input
                  aria-label="Delivery note"
                  value={recvNotes}
                  onChange={(e) => setRecvNotes(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="Optional note"
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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {canReceive ? (
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
                <span className="mt-1 block text-[11px] text-text2">Leave blank to use a saved buying price above zero. Type 0 only with Free stock.</span>
              </label>
              ) : null}
              {canBatchPrice ? (
              <label className="text-xs font-semibold text-text2">
                Batch selling price
                <Input
                  aria-label="Batch selling price"
                  type="number"
                  min={0}
                  step={0.01}
                  value={recvSell}
                  placeholder="Normal product price"
                  onChange={(e) => setRecvSell(e.target.value)}
                  className="mt-1 h-11"
                />
                <span className="mt-1 block text-[11px] text-text2">Optional. Blank uses the normal product price for this batch only.</span>
              </label>
              ) : null}
              <label className="text-xs font-semibold text-text2">
                Additional delivery cost
                <Input
                  aria-label="Additional delivery cost"
                  type="number"
                  min={0}
                  step={0.01}
                  value={recvExtra}
                  onChange={(e) => setRecvExtra(e.target.value)}
                  className="mt-1 h-11"
                  placeholder="0 if none. Split by buy value."
                />
              </label>
              {canReceive ? (
                <label className="flex items-center gap-2 text-sm text-text">
                  <input aria-label="Free stock" type="checkbox" checked={recvFree} onChange={(e) => setRecvFree(e.target.checked)} />
                  Free stock (explicit zero buying price)
                </label>
              ) : null}
              <label className="flex items-center gap-2 text-sm text-text">
                <input aria-label="Confirm extra quantity" type="checkbox" checked={recvExcess} onChange={(e) => setRecvExcess(e.target.checked)} />
                Confirm extra quantity above the order
              </label>
              </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="text-xs font-semibold text-text2">
                Paid now
                <Input aria-label="Paid now" type="number" min={0} step={0.01} value={recvPaid} onChange={(e) => setRecvPaid(e.target.value)} className="mt-1 h-11" placeholder="0 if unpaid" />
              </label>
              <label className="text-xs font-semibold text-text2">
                Pay method
                <Input aria-label="Pay method" value={recvPayMethod} onChange={(e) => setRecvPayMethod(e.target.value)} className="mt-1 h-11" />
              </label>
              <label className="text-xs font-semibold text-text2">
                Pay reference
                <Input aria-label="Pay reference" value={recvPayRef} onChange={(e) => setRecvPayRef(e.target.value)} className="mt-1 h-11" />
              </label>
              <label className="text-xs font-semibold text-text2">
                Due date
                <Input aria-label="Due date" value={recvDue} onChange={(e) => setRecvDue(e.target.value)} className="mt-1 h-11" placeholder="YYYY-MM-DD" />
              </label>
              <BusinessDateField label="Delivery date" value={recvDate} onChange={setRecvDate} confirmed={recvDateConfirmed} onConfirm={setRecvDateConfirmed} reason={recvBackdateReason} onReason={setRecvBackdateReason} />
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                const productForQty = products.find((p) => p.id === Number(recvId));
                const parsedQty = parseQuantity(recvQty || "0", productForQty?.unit, { allowZero: true });
                const parsedRejected = parseQuantity(recvRejected.trim() === "" ? "0" : recvRejected, productForQty?.unit, { allowZero: true });
                const parsedOrdered = recvOrdered.trim() === ""
                  ? null
                  : parseQuantity(recvOrdered, productForQty?.unit, { allowZero: true });
                if (!recvId || "error" in parsedQty) {
                  setRecvMsg("error" in parsedQty ? parsedQty.error : "Select a product and a quantity before adding a line.");
                  return;
                }
                if ("error" in parsedRejected) {
                  setRecvMsg(parsedRejected.error);
                  return;
                }
                if (parsedOrdered && "error" in parsedOrdered) {
                  setRecvMsg(parsedOrdered.error);
                  return;
                }
                const qty = parsedQty.quantity;
                const rejected = parsedRejected.quantity;
                const ordered = parsedOrdered && !("error" in parsedOrdered) ? parsedOrdered.quantity : null;
                if (qty <= 0 && rejected <= 0) {
                  setRecvMsg("Enter a quantity received, or a rejected quantity for goods that must not enter stock.");
                  return;
                }
                if (ordered && qty + rejected - ordered > 0.00001 && !recvExcess) {
                  setRecvMsg("Received plus rejected is above the ordered quantity. Confirm the extra quantity, or reduce the line.");
                  return;
                }
                const cost = recvCost.trim() === "" ? null : Number(recvCost);
                const sell = recvSell.trim() === "" ? null : Number(recvSell);
                if (sell !== null && (!Number.isFinite(sell) || sell < 0)) {
                  setRecvMsg("Enter a valid batch selling price, or leave it blank.");
                  return;
                }
                if (cost === 0 && !recvFree) {
                  setRecvMsg("Enter a buying price, or tick Free stock. A blank or accidental zero is not posted.");
                  return;
                }
                if (cost !== null && !Number.isFinite(cost)) {
                  setRecvMsg("Enter a valid purchase cost, or leave it blank when the product already has a buying price.");
                  return;
                }
                if (recvLines.some((line) => line.product_id === Number(recvId))) {
                  setRecvMsg("That product is already on this delivery.");
                  return;
                }
                const product = products.find((p) => p.id === Number(recvId));
                setRecvLines((lines) => [
                  ...lines,
                  {
                    product_id: Number(recvId),
                    name: product?.name || "Product",
                    sku: product?.sku || "",
                    unit: product?.unit || "pcs",
                    quantity: qty,
                    unit_cost: recvFree ? 0 : cost,
                    rejected_qty: rejected,
                    ordered_qty: ordered && ordered > 0 ? ordered : null,
                    explicit_zero: Boolean(recvFree && cost === 0),
                    allow_excess: recvExcess,
                    sell_price: sell,
                  },
                ]);
                setRecvRejected("");
                setRecvSell("");
                setRecvOrdered("");
                setRecvFree(false);
                setRecvExcess(false);
                setRecvMsg("");
              }}
            >
              Add product to this delivery
            </Button>
            {recvLines.length ? (
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="bg-card text-left text-xs uppercase tracking-wide text-text2">
                    <tr>
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Product</th>
                      <th className="px-3 py-2">Qty received</th>
                      <th className="px-3 py-2">Rejected</th>
                      <th className="px-3 py-2">Unit cost</th>
                      {canBatchPrice ? <th className="px-3 py-2">Batch price</th> : null}
                      <th className="px-3 py-2 text-right">Line total</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {recvLines.map((line, index) => {
                      const product = products.find((p) => p.id === line.product_id);
                      const cost = line.unit_cost == null ? Number(product?.cost_price || 0) : line.unit_cost;
                      return (
                        <tr key={line.product_id} className="border-t border-border">
                          <td className="px-3 py-2 text-text2">{index + 1}</td>
                          <td className="px-3 py-2">
                            <div className="font-semibold text-text">{line.name}</div>
                            <div className="text-xs text-text2">{line.sku || "—"} · {line.unit || "pcs"}</div>
                          </td>
                          <td className="px-3 py-2">
                            <Input
                              aria-label={`Quantity for ${line.name}`}
                              inputMode="decimal"
                              value={String(line.quantity)}
                              onChange={(e) => {
                                const raw = e.target.value;
                                setRecvLines((lines) => lines.map((item) => (
                                  item.product_id === line.product_id ? { ...item, quantity: raw } : item
                                )));
                              }}
                              className="h-10 w-28"
                            />
                          </td>
                          <td className="px-3 py-2 tabular-nums text-text2">
                            {Number(line.rejected_qty || 0)}
                            {line.ordered_qty ? ` · ordered ${line.ordered_qty}` : ""}
                          </td>
                          <td className="px-3 py-2">
                            <Input
                              aria-label={`Unit cost for ${line.name}`}
                              type="number"
                              min={0}
                              step="0.01"
                              value={line.unit_cost ?? ""}
                              placeholder="Current cost"
                              onChange={(e) => {
                                const raw = e.target.value;
                                setRecvLines((lines) => lines.map((item) => (
                                  item.product_id === line.product_id
                                    ? { ...item, unit_cost: raw.trim() === "" ? null : Number(raw) }
                                    : item
                                )));
                              }}
                              className="h-10 w-32"
                            />
                          </td>
                          {canBatchPrice ? <td className="px-3 py-2">
                            <Input
                              aria-label={`Batch selling price for ${line.name}`}
                              type="number"
                              min={0}
                              step="0.01"
                              value={line.sell_price ?? ""}
                              placeholder="Normal"
                              onChange={(e) => {
                                const raw = e.target.value;
                                setRecvLines((lines) => lines.map((item) => (
                                  item.product_id === line.product_id
                                    ? { ...item, sell_price: raw.trim() === "" ? null : Number(raw) }
                                    : item
                                )));
                              }}
                              className="h-10 w-28"
                            />
                          </td> : null}
                          <td className="px-3 py-2 text-right tabular-nums font-semibold text-text">
                            {((Number(line.quantity) || 0) * cost).toFixed(2)}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <button
                              type="button"
                              className="text-xs font-semibold text-err"
                              onClick={() => setRecvLines((lines) => lines.filter((item) => item.product_id !== line.product_id))}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="border-t border-border px-3 py-3 text-right font-extrabold text-text">
                  {(() => {
                    const goods = recvLines.reduce((sum, line) => {
                      const product = products.find((p) => p.id === line.product_id);
                      const cost = line.unit_cost == null ? Number(product?.cost_price || 0) : line.unit_cost;
                      return sum + (Number(line.quantity) || 0) * (Number.isFinite(cost) ? cost : 0);
                    }, 0);
                    const extra = recvExtra.trim() === "" ? 0 : Number(recvExtra);
                    const extraSafe = Number.isFinite(extra) && extra > 0 ? extra : 0;
                    return `Goods ${goods.toFixed(2)} · Additional ${extraSafe.toFixed(2)} · Delivery total ${(goods + extraSafe).toFixed(2)}`;
                  })()}
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
                  const lines = [];
                  if (recvLines.length) {
                    for (const line of recvLines) {
                      const parsed = parseQuantity(String(line.quantity), line.unit, {
                        allowZero: Number(line.rejected_qty || 0) > 0,
                      });
                      if ("error" in parsed) {
                        setRecvMsg(`${line.name}: ${parsed.error}`);
                        return;
                      }
                      lines.push({
                        product_id: line.product_id,
                        quantity: parsed.quantity,
                        unit_cost: line.unit_cost,
                        rejected_qty: Number(line.rejected_qty || 0),
                        ordered_qty: line.ordered_qty,
                        explicit_zero: Boolean(line.explicit_zero),
                        allow_excess: Boolean(line.allow_excess),
                        sell_price: line.sell_price ?? null,
                      });
                    }
                  } else {
                    const parsed = parseQuantity(String(recvQty));
                    if ("error" in parsed) {
                      setRecvMsg(parsed.error);
                      return;
                    }
                    lines.push({
                      product_id: Number(recvId),
                      quantity: parsed.quantity,
                      unit_cost: recvCost.trim() === "" ? null : Number(recvCost),
                      sell_price: recvSell.trim() === "" ? null : Number(recvSell),
                    });
                  }
                  if (recvDate < shopTodayISO() && !canPostBusinessDay() && !recvDateConfirmed) {
                    setRecvMsg("Confirm the backdated delivery date. Stock is not received until a different administrator approves it.");
                    return;
                  }
                  if (recvDate < shopTodayISO() && !canPostBusinessDay() && (recvBackdateReason.trim().length < 3 || recvBackdateReason.trim() === "Other")) {
                    setRecvMsg("Choose a reason for this past date. If you choose Other, write what happened.");
                    return;
                  }
                  if (!recvTokenRef.current) {
                    recvTokenRef.current =
                      typeof crypto !== "undefined" && crypto.randomUUID
                        ? crypto.randomUUID()
                        : `web-recv-${supplierId}`;
                  }
                  const res = await POST<any>("/stock-receipts", {
                    supplier_id: supplierId,
                    notes: recvNotes.trim(),
                    reference: recvReference.trim(),
                    client_token: recvTokenRef.current,
                    payment_amount: recvPaid.trim() === "" ? 0 : Number(recvPaid),
                    payment_method: recvPayMethod,
                    payment_reference: recvPayRef.trim(),
                    due_date: recvDue.trim(),
                    effective_date: recvDate,
                    backdate_reason: recvBackdateReason.trim(),
                    delivery_extra: recvExtra.trim() === "" ? 0 : Number(recvExtra),
                    lines,
                  });
                  if (res?.pending_approval) {
                    setRecvMsg(`${res.reference} is pending approval. Stock was not received.`);
                    setRecvDate(shopTodayISO());
                    setRecvDateConfirmed(false);
                    return;
                  }
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
                  const savedReference = recvReference.trim();
                  const savedNotes = recvNotes.trim();
                  setRecvLines([]);
                  setRecvReference("");
                  setRecvNotes("");
                  await qc.invalidateQueries({ queryKey: ["products"] });
                  await qc.invalidateQueries({ queryKey: ["stock-receipts"] });
                  if (res.duplicate || !(res.lines || []).length) {
                    const fresh = await GET<StockReceipt[]>("/stock-receipts");
                    const opened = (Array.isArray(fresh) ? fresh : []).find(
                      (row) => row.receipt_number === res.receipt_number,
                    );
                    if (opened) setReceipt(opened);
                  } else {
                    setReceipt({
                      id: Number(res.receipt_id || 0),
                      receipt_number: res.receipt_number,
                      supplier_name: res.supplier_name,
                      grand_total: res.grand_total,
                      reference: savedReference,
                      notes: savedNotes,
                      status: "posted",
                      grouped: true,
                      username: user?.username || user?.full_name,
                      amount_paid: res.amount_paid,
                      outstanding: res.outstanding,
                      payment_status: res.payment_status,
                      reference_note: savedReference,
                      lines: (res.lines || []).map((line: any) => ({
                        product_id: line.product_id,
                        product_name: line.product_name || line.name,
                        sku: line.sku,
                        unit: line.unit,
                        quantity: line.quantity,
                        rejected_qty: line.rejected_qty,
                        ordered_qty: line.ordered_qty,
                        unit_cost: line.unit_cost,
                        line_total: line.line_total,
                        old_stock: line.old_stock,
                        new_stock: line.new_stock,
                      })),
                    });
                  }
                } finally {
                  setRecvBusy(false);
                }
              }}
            >
              {recvBusy ? "Saving delivery…" : "Save supplier delivery"}
            </Button>
            {recvMsg ? <div className="text-sm text-text2">{recvMsg}</div> : null}
            {(Array.isArray(receiptsQ.data) ? receiptsQ.data : []).slice(0, 6).length ? (
              <div className="border-t border-border pt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-text2">Recent deliveries</div>
                <div className="mt-2 space-y-1">
                  {(Array.isArray(receiptsQ.data) ? receiptsQ.data : []).slice(0, 6).map((row) => (
                    <button
                      key={`${row.receipt_number}-${row.id}`}
                      type="button"
                      className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-card"
                      onClick={async () => {
                        const full = row.id ? await GET<StockReceipt>(`/stock-receipts/${row.id}`) : row;
                        setReceipt(full && !("error" in (full as object)) ? full : row);
                      }}
                    >
                      <span className="min-w-0 truncate font-semibold text-text">{row.receipt_number || "Delivery"} · {row.supplier_name || "Supplier"}</span>
                      <span className="shrink-0 tabular-nums text-text2">{row.status === "reversed" ? "VOIDED" : (row.payment_status || Number(row.grand_total || 0).toFixed(2))}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </Card>
        </WorkPanel>
      ) : null}
      <PageHeader
        eyebrow="Operations"
        title="Inventory"
        icon={<Package className="h-4 w-4" />}
        description={(() => {
          const warnings = products.filter((p) => (p.cost_health?.badges || []).some((badge) => badge.code !== "complete")).length;
          const incomplete = warnings || valuationQ.data?.costing_incomplete ? " · valuation incomplete where a buying price or FIFO layer is missing" : "";
          const valueText = showStockValue && totalValue != null ? ` · ${KES(totalValue, currency)} FIFO value` : "";
          return `${products.length} SKUs${valueText}${lowCount ? ` · ${lowCount} low` : ""}${warnings ? ` · ${warnings} costing warnings` : ""}${incomplete}`;
        })()}
        actions={
          <Button
            variant="ghost"
            disabled={refreshing}
            onClick={() => void refreshInventory()}
            className="min-h-[44px]"
          >
            <RefreshCw className="h-4 w-4" /> {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2" aria-label="Inventory actions">
        {canCreate ? (
          <Button variant="primary" className="min-h-[44px]" onClick={() => setShowAdd(true)}>+ Add Product</Button>
        ) : null}
        {canManageCategories || canCreateCategory ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("categories")}>Shop Categories</Button>
        ) : null}
        {canReceive ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("receive")}>Receive Stock</Button>
        ) : null}
        {canRestock ? (
          <Link to="/restock" className="inline-flex min-h-[44px] items-center rounded-lg border border-border bg-card px-4 text-sm font-semibold text-text hover:bg-hover">Restock Lists</Link>
        ) : null}
        <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("batches")}>Batches</Button>
        <Link to="/issues" className="inline-flex min-h-[44px] items-center rounded-lg border border-border bg-card px-4 text-sm font-semibold text-text hover:bg-hover">Issues</Link>
        {canStocktake ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("stocktake")}>Stocktake</Button>
        ) : null}
        {canAdjust ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("adjust")}>Adjust Stock</Button>
        ) : null}
        {canOpenRequests ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("requests")}>Adjustment Requests</Button>
        ) : null}
        {canViewSuppliers ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={() => setPanel("suppliers")}>Suppliers</Button>
        ) : null}
        {canExport ? (
          <Button variant="secondary" className="min-h-[44px]" onClick={exportVisible}>
            <Download className="h-4 w-4" /> Export Excel
          </Button>
        ) : null}
        <Button variant="ghost" className="min-h-[44px]" disabled={refreshing} onClick={() => void refreshInventory()}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      {panel === "stocktake" && canStocktake ? (
        <WorkPanel title="Stocktake" onClose={() => setPanel(null)}>
      <Card className="mb-3">
        <form
          className="space-y-3 p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setStocktakeMsg("");
            let id = stocktakeId;
            if (!id) {
              const opened = await POST<any>("/stocktakes", { name: stocktakeName });
              if (!opened?.success) {
                setStocktakeMsg(opened?.error || "Could not start the count");
                return;
              }
              id = Number(opened.id);
              setStocktakeId(id);
            }
            const countedProduct = products.find((p) => p.id === Number(stocktakeProduct));
            const counted = parseQuantity(stocktakeQty, countedProduct?.unit, { allowZero: true });
            if (!stocktakeProduct || "error" in counted) {
              setStocktakeMsg("error" in counted
                ? (counted.error.includes("whole units")
                  ? `${countedProduct?.name || "This product"} is sold in whole units.`
                  : counted.error)
                : "Choose a product and a counted quantity.");
              return;
            }
            const saved = await POST<any>(`/stocktakes/${id}/counts`, {
              product_id: Number(stocktakeProduct),
              counted_qty: counted.quantity,
            });
            setStocktakeMsg(saved?.success
              ? "Count saved. Stock is unchanged until a Super-Admin applies it."
              : (saved?.error || "Could not save the count"));
            if (saved?.success) qc.invalidateQueries({ queryKey: ["stocktakes"] });
          }}
        >
          <div className="text-sm font-extrabold text-text">Stocktake</div>
          <div className="text-xs text-text2">
            Count first. Sales during the count stay. Applying adds the difference to the stock that exists then.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <Input aria-label="Stocktake name" value={stocktakeName} placeholder="Monday morning"
              onChange={(e) => setStocktakeName(e.target.value)} className="h-11" />
            <select aria-label="Product to count" value={stocktakeProduct}
              onChange={(e) => setStocktakeProduct(e.target.value)}
              className="h-11 rounded-xl border border-border bg-panel px-3 text-sm">
              <option value="">Product</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <BusinessDateField label="Stocktake date" value={stocktakeDate} onChange={setStocktakeDate} reason={stocktakeBackdate} onReason={setStocktakeBackdate} />
            <Input aria-label="Counted quantity" type="number" min={0} step="0.01" value={stocktakeQty}
              onChange={(e) => setStocktakeQty(e.target.value)} className="h-11" placeholder="Counted" />
            <Button type="submit" variant="secondary" className="min-h-[44px]">Save count</Button>
          </div>
          {canAdjust && stocktakeId ? (
            <Button
              type="button"
              variant="primary"
              className="min-h-[44px]"
              onClick={async () => {
                if (stocktakeDate < shopTodayISO() && (stocktakeBackdate.trim().length < 3 || stocktakeBackdate.trim() === "Other")) {
                  setStocktakeMsg("Choose a reason for this past stocktake date. If you choose Other, write what happened.");
                  return;
                }
                const applied = await POST<any>(`/stocktakes/${stocktakeId}/apply`, {
                  business_date: stocktakeDate,
                  backdate_reason: stocktakeBackdate.trim(),
                });
                setStocktakeMsg(applied?.success
                  ? "Count applied."
                  : (applied?.error || "Could not apply the count"));
                if (applied?.success) {
                  setStocktakeId(null);
                  qc.invalidateQueries({ queryKey: ["products"] });
                  qc.invalidateQueries({ queryKey: ["stocktakes"] });
                }
              }}
            >
              Apply count
            </Button>
          ) : null}
          {stocktakeMsg ? <div className="text-sm text-text2">{stocktakeMsg}</div> : null}
          <div className="grid gap-2">
            {(stocktakesQ.data?.stocktakes || []).slice(0, 8).map((row) => (
              <button
                key={row.id}
                type="button"
                className="rounded-xl border border-border px-3 py-2 text-left text-sm"
                onClick={async () => {
                  const detail = await GET<any>(`/stocktakes/${row.id}`);
                  const line = detail?.lines?.[0];
                  setStocktakeId(detail?.status === "open" ? Number(detail.id) : null);
                  setStocktakeName(detail?.name || "");
                  setStocktakeMsg(line
                    ? `${detail.name} is ${detail.status}. ${line.name}: counted ${line.counted_qty}, snapshot ${line.snapshot_qty}.`
                    : `${detail?.name || "Count"} is ${detail?.status || "unknown"}.`);
                }}
              >
                {row.name || "Count"} · {row.status}
              </button>
            ))}
          </div>
        </form>
      </Card>
        </WorkPanel>
      ) : null}

      {panel === "requests" && canReceive && !canAdjust ? (
        <Card className="mb-3">
          <form
            className="space-y-3 p-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              const askProduct = products.find((p) => p.id === Number(data.get("product_id")));
              const asked = parseQuantity(String(data.get("requested_qty") || ""), askProduct?.unit, { allowZero: true });
              if ("error" in asked) {
                setRecvMsg(asked.error.includes("whole units")
                  ? `${askProduct?.name || "This product"} is sold in whole units.`
                  : asked.error);
                return;
              }
              const res = await POST<any>("/stock-adjustment-requests", {
                product_id: Number(data.get("product_id")),
                requested_qty: asked.quantity,
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
      {panel === "requests" && canAdjust ? (
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
                  <span className="text-text2"> · {row.reason} · {row.username || "Staff"} · {row.created_at || ""} · {row.status || "pending"}</span>
                </span>
                {user?.id != null && Number(row.user_id) === Number(user.id) ? (
                  <span className="text-xs text-text2">You cannot approve your own request.</span>
                ) : (
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
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {panel === "suppliers" && canViewSuppliers ? (
        <WorkPanel title="Suppliers" onClose={() => setPanel(null)}>
          <SuppliersPanel canManage={canManageSuppliers} />
        </WorkPanel>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
          <Input
            aria-label="Search products"
            placeholder="Search name, SKU, or barcode…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
            className="pl-8 min-h-[44px]"
          />
        </div>
        <select
          aria-label="Product status"
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="h-11 rounded-xl border border-border bg-input px-3 text-sm text-text"
        >
          <option value="all">All products</option>
          <option value="in">In stock</option>
          <option value="low">Low stock</option>
          <option value="out">Out of stock</option>
        </select>
        <select
          aria-label="Product category"
          value={categoryOptions.some((name) => name.toLowerCase() === categoryFilter.toLowerCase()) || categoryFilter === "all" || categoryFilter === UNCATEGORISED ? categoryFilter : "all"}
          onChange={(e) => { setCategoryFilter(e.target.value); setPage(0); }}
          className="h-11 max-w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
        >
          <option value="all">All categories</option>
          {categoryOptions.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
          <option value={UNCATEGORISED}>Uncategorised</option>
        </select>
        <select
          aria-label="Sort products"
          value={sortMode}
          onChange={(e) => { setSortMode(e.target.value as InventorySort); setPage(0); }}
          className="h-11 rounded-xl border border-border bg-input px-3 text-sm text-text"
        >
          <option value="name_asc">Name A–Z</option>
          <option value="name_desc">Name Z–A</option>
          <option value="stock_asc">Lowest stock first</option>
          <option value="stock_desc">Highest stock first</option>
          <option value="created">Recently added</option>
          <option value="updated">Recently updated</option>
          {sortMode === "price_asc" || sortMode === "price_desc" ? <option value={sortMode}>Price</option> : null}
          {sortMode === "category_asc" || sortMode === "category_desc" ? <option value={sortMode}>Category</option> : null}
        </select>
        <select
          aria-label="Costing filter"
          value={costFilter}
          onChange={(e) => { setCostFilter(e.target.value); setPage(0); }}
          className="h-11 rounded-xl border border-border bg-input px-3 text-sm text-text"
        >
          <option value="">All costing</option>
          <option value="missing_price">Missing buying price</option>
          <option value="zero_or_invalid">Zero or invalid cost</option>
          <option value="missing_fifo">Missing FIFO layer</option>
          <option value="stock_without_cost">Stock without cost</option>
          <option value="inconsistent">Costing needs review</option>
          <option value="complete">Costing complete</option>
        </select>
        <span className="text-sm font-semibold text-text" aria-label="Matching products">
          {list.length} {list.length === 1 ? "product" : "products"}
        </span>
        <Button
          type="button"
          variant="secondary"
          className="min-h-[44px]"
          onClick={() => {
            setQ("");
            setStatusFilter("all");
            setCategoryFilter("all");
            setSortMode("name_asc");
            setCostFilter("");
            setPage(0);
          }}
        >
          Clear filters
        </Button>
      </div>
      <Card className="overflow-hidden">
        {productsQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading inventory…</div>
        ) : (
          <>
            {!productsQ.isLoading && list.length === 0 ? (
              <div className="px-4 py-6 text-sm text-text2">No products match these filters.</div>
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
                ...(canEdit || canRemove ? ["Actions"] : []),
              ]}
            >
              {pageRows.map((p) => {
                const band = stockBand(p);
                const oos = band === "out";
                const low = band === "low";
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
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(p.cost_health?.badges || []).filter((badge) => badge.code !== "complete").map((badge) => (
                          <Badge key={badge.code} tone={badge.tone === "err" ? "err" : badge.tone === "ok" ? "ok" : "warn"}>
                            {badge.label}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.sku || "—"}</td>
                    <td className="px-4 py-2.5 text-text2">{p.category || "Uncategorised"}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                      {KES(p.price, currency)}
                    </td>
                    {seeCost ? (
                      <td className="px-4 py-2.5 tabular-nums text-text2">
                        {p.cost_price == null ? "—" : KES(p.cost_price, currency)}
                      </td>
                    ) : null}
                    <td className="px-4 py-2.5 tabular-nums">
                      <Badge tone={oos ? "err" : low ? "warn" : "muted"}>{p.stock ?? 0}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-text2">{p.unit || "pcs"}</td>
                    {canEdit || canRemove ? (
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-2">
                          {canEdit ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                loadEdit(p);
                                setPanel("edit");
                              }}
                            >
                              Edit
                            </Button>
                          ) : null}
                          {canRemove ? (
                            <Button variant="danger" size="sm" onClick={() => archiveProduct(p)}>
                              Remove
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </Table>
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-border text-xs text-text2">
              <span>
                Page {safePage + 1} / {pageCount} · {list.length} shown
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={safePage <= 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Prev
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={safePage >= pageCount - 1}
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
                <label className="text-xs text-text2">{seeCost ? "Cost" : "Buying price"}
                  <Input aria-label="Buying price" className="mt-1 h-11" type="number" min={0} step={0.01} value={newProduct.cost_price} onChange={(e) => setNewProduct({ ...newProduct, cost_price: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Opening stock
                  <Input className="mt-1 h-11" type="number" min={0} value={newProduct.stock} onChange={(e) => setNewProduct({ ...newProduct, stock: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Unit
                  <Input className="mt-1 h-11" value={newProduct.unit} onChange={(e) => setNewProduct({ ...newProduct, unit: e.target.value })} />
                </label>
                <label className="text-xs text-text2">Decimal quantities
                  <select aria-label="Decimal quantities" className="mt-1 h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text" value={newProduct.decimal_qty} onChange={(e) => setNewProduct({ ...newProduct, decimal_qty: e.target.value })}>
                    <option value="">Follow the unit</option>
                    <option value="1">Allow decimal quantities</option>
                    <option value="0">Whole quantities only</option>
                  </select>
                </label>
                <label className="text-xs text-text2 sm:col-span-2">Category
                  <CategoryField
                    value={newProduct.category}
                    canCreate={canCreateCategory}
                    onChange={(category) => setNewProduct({ ...newProduct, category })}
                  />
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
                      const created = await POST<{ success?: boolean; id?: number; error?: string; pending_approval?: boolean; message?: string }>("/products", {
                        name: newProduct.name.trim(),
                        sku: newProduct.sku.trim(),
                        category: newProduct.category.trim(),
                        price: Number(newProduct.price || 0),
                        cost_price: newProduct.cost_price.trim() === "" ? null : Number(newProduct.cost_price),
                        explicit_zero: newProduct.cost_price.trim() !== "" && Number(newProduct.cost_price) === 0,
                        stock: Number(newProduct.stock || 0),
                        unit: newProduct.unit.trim() || "pcs",
                        allow_decimal_qty: newProduct.decimal_qty === "" ? null : Number(newProduct.decimal_qty),
                        barcode: newProduct.barcode.trim(),
                      });
                      if (!created || created.error || (!created.id && !created.pending_approval)) {
                        toast.error(created?.error || "The product was not saved.");
                        return;
                      }
                      if (created.pending_approval) {
                        toast.success(created.message || "Waiting for an administrator. The product was not published.");
                        setShowAdd(false);
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
                      setNewProduct({ name: "", sku: "", category: "", price: "", cost_price: "", stock: "0", unit: "pcs", decimal_qty: "", barcode: "" });
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
                <div className="flex gap-2">
                  {canEdit ? (
                    <Button variant="secondary" onClick={() => { setProductDetail(null); setPanel("edit"); }}>
                      Edit product details
                    </Button>
                  ) : null}
                  <Button variant="ghost" onClick={() => setProductDetail(null)}>
                    Close
                  </Button>
                </div>
              </div>
              <div className="px-5 pt-4">
                <ProductPhoto
                  src={productDetail.image_path}
                  size="lg"
                  onFile={canEdit ? async (file) => {
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
                  } : undefined}
                  onRemove={canEdit && productDetail.image_path ? async () => {
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
                <div className="rounded-xl border border-border p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-text2">Purchase batches</div>
                  {historyQ.data?.batch_summary ? (
                    <p className="mt-1 text-sm text-text">
                      {historyQ.data.batch_summary.active_batches || 0} open
                      {historyQ.data.see_cost
                        ? ` · value ${KES(historyQ.data.batch_summary.inventory_value || 0)} · average ${KES(historyQ.data.batch_summary.average_cost || 0)}`
                        : ""}
                    </p>
                  ) : null}
                  <div className="mt-2 space-y-1 text-sm">
                    {(historyQ.data?.batches || []).map((batch: any) => (
                      <div key={batch.id} className="flex justify-between gap-3 text-text2">
                        <span>
                          {batch.batch_ref || `#${batch.id}`} {batch.supplier_name || (batch.legacy ? "Opening stock" : "Batch")}
                          {batch.cost_origin === "inherited" ? " · inherited" : ""}
                          {batch.reference_note ? ` · ${batch.reference_note}` : ""} · left {batch.remaining_qty}
                        </span>
                        <span className="flex items-center gap-3">
                        {historyQ.data?.see_cost ? (
                          <span>
                            buy {KES(batch.purchase_unit_cost || batch.unit_cost || 0)}
                            {Number(batch.extra_unit_cost) ? ` + ${KES(batch.extra_unit_cost)}` : ""}
                            {" · landed "}{KES(batch.unit_cost || 0)}
                            {batch.price_mode === "custom"
                              ? ` · sells ${KES(batch.effective_sell_price || 0)} (custom)`
                              : batch.effective_sell_price != null
                                ? ` · sells ${KES(batch.effective_sell_price)}`
                                : ""}
                          </span>
                        ) : batch.effective_sell_price != null ? (
                          <span>
                            sells {KES(batch.effective_sell_price)}
                            {batch.price_mode === "custom" ? " (custom)" : ""}
                          </span>
                        ) : null}
                        {historyQ.data?.can_set_batch_price && batch.status !== "exhausted" ? (
                          <button
                            type="button"
                            className="text-xs font-semibold text-primary"
                            onClick={async () => {
                              const current = batch.sell_price == null ? "" : String(batch.sell_price);
                              const entered = window.prompt(
                                "Selling price for this batch. Leave blank to use the normal product price.",
                                current,
                              );
                              if (entered === null) return;
                              const trimmed = entered.trim();
                              if (trimmed !== "") {
                                const number = Number(trimmed);
                                if (!Number.isFinite(number) || number < 0) {
                                  toast.error("Enter a valid selling price.");
                                  return;
                                }
                                const normal = Number(productDetail?.price || 0);
                                if (number > normal + 0.001 && !window.confirm(
                                  `This batch price is above the normal product price of ${KES(normal)}. Save it?`,
                                )) return;
                              }
                              const res = await POST<any>(`/cost-layers/${batch.id}/sell-price`, {
                                sell_price: trimmed === "" ? null : Number(trimmed),
                              });
                              if (!res || res.error) toast.error(res?.error || "The price was not saved.");
                              else {
                                if (res.warning) toast.warning(res.warning);
                                else toast.success("Batch selling price saved.");
                                qc.invalidateQueries({ queryKey: ["product-history", productDetail?.id] });
                              }
                            }}
                          >
                            Set price
                          </button>
                        ) : null}
                        </span>
                      </div>
                    ))}
                    {historyQ.data && !(historyQ.data.batches || []).length ? (
                      <div className="text-text2">No purchase batch is recorded for this product.</div>
                    ) : null}
                  </div>
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
          className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-4"
          onClick={() => setReceipt(null)}
        >
          <div className="mx-auto my-4 w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
          <Card className="overflow-hidden">
            {receipt.lines && receipt.lines.length ? (
              <>
                <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-text2">
                      Goods received note
                    </div>
                    <div className="mt-1 text-lg font-extrabold text-text">
                      {receipt.receipt_number || "Delivery"}
                    </div>
                    <div className="text-sm text-text2">
                      {receipt.supplier_name || "Supplier"}
                      {" · "}
                      {receipt.status === "reversed" ? "Reversed" : "Posted"}
                      {" · "}
                      {String(receipt.created_at || "").replace("T", " ").slice(0, 19)}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={async () => {
                        if (!receipt.id) return;
                        const doc = await GET<{ text?: string; error?: string }>(`/stock-receipts/${receipt.id}/document`);
                        if (doc?.text) setReceipt({ ...receipt, grn_text: doc.text });
                      }}
                    >
                      Print / preview
                    </Button>
                    <Button variant="ghost" onClick={() => setReceipt(null)}>
                      Close
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 px-5 py-4 text-sm">
                  {[
                    ["Supplier", receipt.supplier_name || "No supplier"],
                    ["Invoice reference", receipt.reference || receipt.reference_note || "—"],
                    ["Delivery note", receipt.notes || "—"],
                    ["Received by", receipt.username || "—"],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <div className="text-xs text-text2">{label}</div>
                      <div className="mt-1 font-semibold text-text">{value}</div>
                    </div>
                  ))}
                </div>
                <div className="overflow-x-auto border-t border-border">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead className="bg-card text-left text-xs uppercase tracking-wide text-text2">
                      <tr>
                        <th className="px-3 py-2">#</th>
                        <th className="px-3 py-2">Product</th>
                        <th className="px-3 py-2 text-right">Qty</th>
                        <th className="px-3 py-2 text-right">Unit cost</th>
                        <th className="px-3 py-2 text-right">Line total</th>
                        <th className="px-3 py-2 text-right">Stock</th>
                      </tr>
                    </thead>
                    <tbody>
                      {receipt.lines.map((line, index) => (
                        <tr key={`${line.product_name}-${index}`} className="border-t border-border">
                          <td className="px-3 py-2 text-text2">{index + 1}</td>
                          <td className="px-3 py-2">
                            <div className="font-semibold text-text">{line.product_name}</div>
                            <div className="text-xs text-text2">{line.sku || "—"} · {line.unit || "pcs"}</div>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-text">
                            {Number(line.quantity || 0)}
                            {line.ordered_qty != null ? ` · ordered ${Number(line.ordered_qty)}` : ""}
                            {Number(line.rejected_qty || 0) > 0 ? ` · rejected ${Number(line.rejected_qty)} not stocked` : ""}
                            {Number(line.returned_qty || 0) > 0 ? ` · returned ${Number(line.returned_qty)}` : ""}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-text">{Number(line.unit_cost || 0).toFixed(2)}</td>
                          <td className="px-3 py-2 text-right tabular-nums font-semibold text-text">{Number(line.line_total || 0).toFixed(2)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-text2">
                            {line.old_stock != null && line.new_stock != null
                              ? `${Number(line.old_stock)} → ${Number(line.new_stock)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border-t border-border px-5 py-4 text-sm text-text">
                  <div className="text-base font-extrabold">
                    Invoice {Number(receipt.grand_total || 0).toFixed(2)} · Paid {Number(receipt.amount_paid || 0).toFixed(2)} · Outstanding {receipt.status === "reversed" ? "0.00" : Number(receipt.outstanding || 0).toFixed(2)} · {receipt.status === "reversed" ? "VOIDED" : (receipt.payment_status || "UNPAID")}
                  </div>
                  {(receipt.payments || []).length ? (
                    <div className="mt-2 space-y-1 text-text2">
                      {receipt.payments?.map((payment) => (
                        <div key={payment.payment_number}>
                          {payment.payment_number} · {payment.method} · {Number(payment.allocated || payment.amount || 0).toFixed(2)} {payment.reference || ""}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {receipt.grn_text ? (
                    <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-border bg-panel p-3 text-xs text-text">{receipt.grn_text}</pre>
                  ) : null}
                  <DeliveryActions
                    receipt={receipt}
                    onChanged={(next) => {
                      setReceipt(next as StockReceipt);
                      qc.invalidateQueries({ queryKey: ["stock-receipts"] });
                    }}
                  />
                </div>
              </>
            ) : (() => {
              const product = products.find((p) => p.id === receipt.product_id);
              const name = receipt.product_name || product?.name || "Product";
              const sku = receipt.sku || product?.sku || "—";
              const category = receipt.category || product?.category || "Uncategorised";
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
                ["Supplier", receipt.supplier_name || "No supplier"],
                ["Quantity received", `+${Number(receipt.qty_change || 0)} ${unit}`],
                ["Stock before", String(Number(receipt.qty_before || 0))],
                ["Stock after", String(Number(receipt.qty_after || 0))],
                ["Received by", receipt.username || "—"],
                ["Delivery note", receipt.notes || receipt.reason || "—"],
              ].map(([label, value]) => (
                <div key={label}>
                  <div className="text-xs text-text2">{label}</div>
                  <div className="mt-1 font-semibold text-text">{value}</div>
                </div>
              ))}
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
          <span className="text-text font-semibold">{list.length}</span>
          {list.length === products.length ? " products" : ` of ${products.length} products`}
          <span className="text-muted-fg mx-2">·</span>
          <span className="text-warn font-semibold">{lowCount}</span> low stock
        </div>
        {showStockValue && totalValue != null ? (
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
