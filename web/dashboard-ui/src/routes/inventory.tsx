import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, RefreshCw, Package, Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST, PUT, DEL, getUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApi, exportQuery } from "@/lib/download";
import { KES, todayISO } from "@/lib/format";
import { SupplierDeliveries } from "@/components/supplier-deliveries";

export const Route = createFileRoute("/inventory")({
  component: Inventory,
});

type Product = {
  id: number;
  name: string;
  sku?: string;
  category?: string;
  price: number;
  cost_price?: number;
  stock: number;
  min_stock?: number;
  unit?: string;
};

type SortKey = "name" | "stock" | "price" | "category";

function Inventory() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || getUser()?.role || "").toLowerCase();
  const canReceive = ["cashier", "manager", "admin", "superadmin"].includes(role);
  const canEdit = ["manager", "admin", "superadmin"].includes(role);
  const canCreate = canReceive;
  const canAdjust = ["admin", "superadmin"].includes(role);
  const canDelete = ["admin", "superadmin"].includes(role);
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [adjPid, setAdjPid] = useState<number | null>(null);
  const [editProduct, setEditProduct] = useState<Partial<Product> | null>(null);
  const pageSize = 40;

  const modulesQ = useQuery({
    queryKey: ["nav-modules"],
    queryFn: () => GET<{ modules?: string[] }>("/nav/modules"),
    staleTime: 5 * 60_000,
  });
  const modules = modulesQ.data?.modules ?? [];
  const canSeeCost = modules.includes("inventory_value");

  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];

  const list = useMemo(() => {
    const filtered = products.filter(
      (p) =>
        q === "" ||
        p.name.toLowerCase().includes(q.toLowerCase()) ||
        (p.sku || "").toLowerCase().includes(q.toLowerCase()) ||
        (p.category || "").toLowerCase().includes(q.toLowerCase()),
    );
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

  const totalValue = canSeeCost
    ? products.reduce(
        (s, p) => s + Number(p.stock || 0) * Number(p.cost_price ?? p.price ?? 0),
        0,
      )
    : products.reduce((s, p) => s + Number(p.stock || 0) * Number(p.price || 0), 0);
  const lowCount = products.filter(
    (p) => Number(p.stock) > 0 && Number(p.stock) <= Number(p.min_stock ?? 5),
  ).length;

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "category" ? "asc" : "desc");
    }
    setPage(0);
  }

  async function exportInv(format: "xlsx" | "csv") {
    if (!canSeeCost) {
      toast.error("Inventory export needs Reports/Accounting access. Ask Super Admin.");
      return;
    }
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

  async function removeProduct(product: Product) {
    if (!canDelete) return;
    const ok = window.confirm(
      `Remove “${product.name}” from the catalogue?\n\n` +
        "It will no longer appear when selling or receiving. Past sales stay on record.",
    );
    if (!ok) return;
    const res = await DEL<any>(`/products/${product.id}`);
    if (res?.success) {
      toast.success(res.message || `${product.name} was removed from the catalogue`);
      qc.invalidateQueries({ queryKey: ["products"] });
    } else {
      toast.error(res?.error || "This product was not removed. Nothing was changed.");
    }
  }

  const sortLabel = (key: SortKey, label: string) => (
    <button type="button" onClick={() => toggleSort(key)} className="hover:text-gold">
      {label} {sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </button>
  );

  const head = [
    sortLabel("name", "Name"),
    "SKU",
    sortLabel("category", "Category"),
    sortLabel("price", "Price"),
    ...(canSeeCost ? ["Cost"] : []),
    sortLabel("stock", "Stock"),
    "Unit",
    ...(canAdjust || canEdit || canDelete ? ["Actions"] : []),
  ];

  return (
    <AppShell title="Inventory">
      <PageHeader
        eyebrow="Operations"
        title="Inventory"
        icon={<Package className="h-4 w-4" />}
        description={
          canSeeCost
            ? `${products.length} SKUs · ${KES(totalValue, currency)} stock value${lowCount ? ` · ${lowCount} low` : ""}`
            : `${products.length} SKUs${lowCount ? ` · ${lowCount} low` : ""} · cost hidden for your role`
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canCreate ? (
              <Button onClick={() => setEditProduct({ name: "", price: 0, cost_price: 0, stock: 0, min_stock: 0, unit: "pcs" })}>
                <Plus className="h-4 w-4" /> Add product
              </Button>
            ) : null}
            <div className="relative flex-1 min-w-[200px] max-w-md">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
              <Input
                placeholder="Search by name, SKU, or category…"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(0);
                }}
                className="pl-8 min-h-[44px]"
              />
            </div>
            {canSeeCost ? (
              <>
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
              </>
            ) : null}
            <Button
              variant="ghost"
              onClick={() => qc.invalidateQueries({ queryKey: ["products"] })}
              className="min-h-[44px]"
            >
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </div>
        }
      />

      <Card className="overflow-hidden">
        {productsQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading inventory…</div>
        ) : (
          <>
            <Table head={head}>
              {pageRows.map((p) => {
                const stock = Number(p.stock) || 0;
                const oos = stock === 0;
                const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
                return (
                  <tr key={p.id}>
                    <td className="px-4 py-2.5 text-text font-medium">{p.name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.sku || "—"}</td>
                    <td className="px-4 py-2.5 text-text2">{p.category || "General"}</td>
                    <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                      {KES(p.price, currency)}
                    </td>
                    {canSeeCost ? (
                      <td className="px-4 py-2.5 tabular-nums text-text2">
                        {KES(p.cost_price ?? 0, currency)}
                      </td>
                    ) : null}
                    <td className="px-4 py-2.5 tabular-nums">
                      <Badge tone={oos ? "err" : low ? "warn" : "muted"}>{stock}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-text2">{p.unit || "pcs"}</td>
                    {canAdjust || canEdit || canDelete ? (
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {canEdit ? (
                            <Button size="sm" variant="ghost" onClick={() => setEditProduct(p)}>
                              Edit
                            </Button>
                          ) : null}
                          {canAdjust ? (
                            <Button size="sm" variant="secondary" onClick={() => setAdjPid(p.id)}>
                              Adjust
                            </Button>
                          ) : null}
                          {canDelete ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => void removeProduct(p)}
                            >
                              Delete
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

      <SupplierDeliveries
        products={products}
        currency={currency}
        canReceive={canReceive}
        onStockChanged={() => qc.invalidateQueries({ queryKey: ["products"] })}
      />

      <div className="mt-3 flex items-center justify-between text-xs text-text2">
        <div>
          <span className="text-text font-semibold">{products.length}</span> products
          <span className="text-muted-fg mx-2">·</span>
          <span className="text-warn font-semibold">{lowCount}</span> low stock
        </div>
        {canSeeCost ? (
          <div>
            Stock value:{" "}
            <span className="text-gold font-bold text-sm tabular-nums">
              {KES(totalValue, currency)}
            </span>
          </div>
        ) : (
          <div className="text-text2">Ask Super Admin for cost / export</div>
        )}
      </div>

      {adjPid != null ? (
        <AdjustModal
          product={products.find((p) => p.id === adjPid)}
          onClose={() => setAdjPid(null)}
          onDone={() => {
            setAdjPid(null);
            qc.invalidateQueries({ queryKey: ["products"] });
          }}
        />
      ) : null}
      {editProduct ? (
        <ProductModal
          product={editProduct}
          canSeeCost={canSeeCost || !editProduct.id}
          onClose={() => setEditProduct(null)}
          onDone={() => {
            setEditProduct(null);
            qc.invalidateQueries({ queryKey: ["products"] });
          }}
        />
      ) : null}
    </AppShell>
  );
}

function AdjustModal({
  product,
  onClose,
  onDone,
}: {
  product?: Product;
  onClose: () => void;
  onDone: () => void;
}) {
  const [direction, setDirection] = useState<"add" | "remove" | "set">("add");
  const [qty, setQty] = useState("1");
  const [reason, setReason] = useState("correction");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  if (!product) return null;

  async function submit() {
    setBusy(true);
    const res = await POST<any>(`/products/${product!.id}/adjust`, {
      direction,
      quantity: Number(qty),
      reason,
      pin,
      expected_stock: product!.stock,
    });
    setBusy(false);
    if (res?.success) {
      toast.success(res.message || "Stock adjusted");
      onDone();
    } else {
      toast.error(res?.error || "Stock was not adjusted. Nothing was changed.");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-text mb-1">Adjust stock</h3>
        <p className="text-sm text-text2 mb-4">
          {product.name} · on hand {product.stock}. Admin access and Super-Admin PIN required.
        </p>
        <div className="space-y-3">
          <label className="block text-xs font-medium text-text2">
            Direction
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-sm text-text"
              value={direction}
              onChange={(e) => setDirection(e.target.value as any)}
            >
              <option value="add">Add</option>
              <option value="remove">Remove</option>
              <option value="set">Set absolute</option>
            </select>
          </label>
          <label className="block text-xs font-medium text-text2">
            Quantity
            <Input value={qty} onChange={(e) => setQty(e.target.value)} type="number" min="0" step="0.01" />
          </label>
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
            Apply
          </Button>
        </div>
      </div>
    </div>
  );
}

function ProductModal({
  product,
  canSeeCost,
  onClose,
  onDone,
}: {
  product: Partial<Product>;
  canSeeCost: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({ ...product });
  const [busy, setBusy] = useState(false);
  const isNew = !form.id;
  async function submit() {
    if (!String(form.name || "").trim() || Number(form.price || 0) <= 0) {
      toast.error("Product name and a selling price above zero are required");
      return;
    }
    if (canSeeCost && Number(form.cost_price || 0) <= 0) {
      toast.error("Enter the buying cost so profit reports remain complete");
      return;
    }
    const payload: Record<string, unknown> = {
      name: String(form.name).trim(),
      sku: form.sku || "",
      category: form.category || "",
      price: Number(form.price || 0),
      min_stock: Number(form.min_stock || 0),
      unit: form.unit || "pcs",
    };
    if (canSeeCost) payload.cost_price = Number(form.cost_price || 0);
    setBusy(true);
    const res = isNew
      ? await POST<any>("/products", payload)
      : await PUT<any>(`/products/${form.id}`, payload);
    setBusy(false);
    if (res?.success || res?.id != null) {
      toast.success(isNew ? "Product added" : "Product updated");
      onDone();
    } else {
      toast.error(res?.error || "This product was not saved. Check the details and try again.");
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="mb-4 text-lg font-semibold text-text">
          {isNew ? "Add product" : `Edit ${form.name}`}
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["name", "Name", "text"],
            ["sku", "SKU / code", "text"],
            ["category", "Category", "text"],
            ["unit", "Unit", "text"],
            ["price", "Selling price", "number"],
            ["min_stock", "Low-stock level", "number"],
            ...(canSeeCost
              ? [["cost_price", isNew ? "Buying cost" : "Buying cost (latest)", "number"]]
              : []),
          ].map(([key, label, type]) => (
            <label key={key} className="text-xs font-medium text-text2">
              {label}
              <Input
                className="mt-1"
                type={type}
                min={type === "number" ? "0" : undefined}
                step={type === "number" ? "0.01" : undefined}
                value={(form as any)[key] ?? ""}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <p className="mt-3 text-xs text-text2">
          Stock is not changed here. Use Receive or protected Adjust Stock. Each supplier delivery
          overwrites the buying cost with what the vendor charged, so it stays the latest cost.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy}>Save product</Button>
        </div>
      </div>
    </div>
  );
}
