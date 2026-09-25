import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Eye, PackageMinus, Pencil, Plus, RotateCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { DEL, GET, POST, PUT, getUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES, todayISO } from "@/lib/format";

export const Route = createFileRoute("/consumption")({
  component: Consumption,
});

type Product = {
  id: number;
  name: string;
  sku?: string;
  stock?: number;
  cost_price?: number;
  price?: number;
  unit?: string;
};

type SelectedLine = Product & { quantity: number };
const TABS = ["New Consumption", "History", "Departments"] as const;

function daysAgo(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function Consumption() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || getUser()?.role || "").toLowerCase();
  const canCreate = ["manager", "admin", "superadmin"].includes(role);
  const canManageDepartments = canCreate;
  const canVoid = ["admin", "superadmin"].includes(role);
  const [tab, setTab] = useState<(typeof TABS)[number]>(
    canCreate ? "New Consumption" : "History",
  );
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";

  return (
    <AppShell title="Internal Consumption">
      <PageHeader
        eyebrow="Inventory"
        title="Internal Consumption"
        icon={<PackageMinus className="h-4 w-4" />}
        description="Stock used by departments, with atomic stock reduction, cost, history and protected void."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((name) => (
          <Button
            key={name}
            size="sm"
            variant={tab === name ? "primary" : "secondary"}
            onClick={() => setTab(name)}
          >
            {name}
          </Button>
        ))}
      </div>
      {tab === "New Consumption" ? (
        <NewConsumption currency={currency} canCreate={canCreate} onSaved={() => {
          qc.invalidateQueries({ queryKey: ["products"] });
          qc.invalidateQueries({ queryKey: ["consumptions"] });
        }} />
      ) : null}
      {tab === "History" ? (
        <ConsumptionHistory currency={currency} canVoid={canVoid} />
      ) : null}
      {tab === "Departments" ? (
        <Departments canManage={canManageDepartments} />
      ) : null}
    </AppShell>
  );
}

function NewConsumption({
  currency,
  canCreate,
  onSaved,
}: {
  currency: string;
  canCreate: boolean;
  onSaved: () => void;
}) {
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const departmentsQ = useQuery({
    queryKey: ["departments-active"],
    queryFn: () => GET<any[]>("/departments"),
  });
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const departments = Array.isArray(departmentsQ.data) ? departmentsQ.data : [];
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Record<number, SelectedLine>>({});
  const [departmentId, setDepartmentId] = useState("");
  const [reason, setReason] = useState("");
  const [takenBy, setTakenBy] = useState("");
  const [notes, setNotes] = useState("");
  const [date, setDate] = useState(todayISO());
  const [busy, setBusy] = useState(false);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return products
      .filter((p) => Number(p.stock || 0) > 0)
      .filter((p) => !needle
        || p.name.toLowerCase().includes(needle)
        || String(p.sku || "").toLowerCase().includes(needle))
      .slice(0, 200);
  }, [products, query]);
  const lines = Object.values(selected);
  const total = lines.reduce(
    (sum, line) => sum + line.quantity * Number(line.cost_price || 0), 0);
  const retailValue = lines.reduce(
    (sum, line) => sum + line.quantity * Number(line.price || 0), 0);

  function toggle(product: Product) {
    setSelected((current) => {
      const next = { ...current };
      if (next[product.id]) delete next[product.id];
      else next[product.id] = { ...product, quantity: 1 };
      return next;
    });
  }

  function setQty(id: number, quantity: number) {
    setSelected((current) => ({
      ...current,
      [id]: { ...current[id], quantity },
    }));
  }

  async function save() {
    if (!canCreate) {
      toast.error("Your role cannot record internal consumption. Ask a Manager or Admin.");
      return;
    }
    if (!departmentId) {
      toast.error("Select the department using the stock");
      return;
    }
    if (!reason.trim()) {
      toast.error("Enter why the stock is being used");
      return;
    }
    if (!lines.length) {
      toast.error("Select at least one product");
      return;
    }
    const bad = lines.find(
      (line) => line.quantity <= 0 || line.quantity > Number(line.stock || 0));
    if (bad) {
      toast.error(
        `${bad.name}: enter a quantity between 0 and ${Number(bad.stock || 0)}`);
      return;
    }
    setBusy(true);
    const result = await POST<any>("/consumptions", {
      date,
      department_id: Number(departmentId),
      reason: reason.trim(),
      taken_by: takenBy.trim(),
      notes: notes.trim(),
      items: lines.map((line) => ({
        product_id: line.id,
        quantity: line.quantity,
      })),
    });
    setBusy(false);
    if (!result?.success) {
      toast.error(result?.error || "Nothing was saved or removed from stock. Try again.");
      return;
    }
    toast.success(`${result.reference_no} saved · ${lines.length} products`);
    setSelected({});
    setReason("");
    setTakenBy("");
    setNotes("");
    onSaved();
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.85fr)]">
      <Card className="p-4">
        <SectionTitle>Select products</SectionTitle>
        <p className="mt-1 text-xs text-text2">
          Tick as many products as needed. Search results remain large and scrollable.
        </p>
        <div className="relative mt-3">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text2" />
          <Input
            className="min-h-[48px] pl-9 text-base"
            placeholder="Search all products by name or SKU…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="mt-3 max-h-[520px] min-h-[360px] overflow-y-auto rounded-lg border border-border">
          {filtered.map((product) => {
            const checked = Boolean(selected[product.id]);
            return (
              <label
                key={product.id}
                className="flex min-h-[54px] cursor-pointer items-center gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-panel"
              >
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-amber-500"
                  checked={checked}
                  onChange={() => toggle(product)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-text">{product.name}</span>
                  <span className="text-xs text-text2">
                    {product.sku || "No SKU"} · {Number(product.stock || 0)} {product.unit || "pcs"} available
                  </span>
                </span>
                {checked ? <Badge tone="ok">Selected</Badge> : null}
              </label>
            );
          })}
          {!productsQ.isLoading && !filtered.length ? (
            <div className="p-8 text-center text-sm text-text2">
              No in-stock products match that search.
            </div>
          ) : null}
        </div>
      </Card>

      <div className="space-y-4">
        <Card className="p-4">
          <SectionTitle>Consumption details</SectionTitle>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-text2">Date
              <Input className="mt-1" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="text-xs font-medium text-text2">Department
              <select className="mt-1 min-h-[40px] w-full rounded-md border border-border bg-panel px-3 text-sm text-text" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
                <option value="">Select department…</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
              {!departments.length ? (
                <p className="mt-1 text-xs text-text2">Add this shop’s departments on the Departments tab. None are created automatically.</p>
              ) : null}
            </label>
            <label className="text-xs font-medium text-text2">Reason
              <Input className="mt-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this stock being used?" />
            </label>
            <label className="text-xs font-medium text-text2">Taken by
              <Input className="mt-1" value={takenBy} onChange={(e) => setTakenBy(e.target.value)} placeholder="Person receiving the items" />
            </label>
          </div>
          <label className="mt-3 block text-xs font-medium text-text2">Notes
            <Input className="mt-1" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional details" />
          </label>
        </Card>
        <Card className="overflow-hidden">
          <div className="border-b border-border p-4">
            <SectionTitle>Selected items ({lines.length})</SectionTitle>
          </div>
          <div className="max-h-[390px] overflow-y-auto">
            <Table head={["Product", "Available", "Quantity", "Cost", ""]}>
              {lines.map((line) => (
                <tr key={line.id}>
                  <td className="px-4 py-2.5 font-medium text-text">{line.name}</td>
                  <td className="px-4 py-2.5 text-text2">{Number(line.stock || 0)}</td>
                  <td className="px-4 py-2.5">
                    <Input
                      className="w-24"
                      type="number"
                      min="0.001"
                      max={Number(line.stock || 0)}
                      step="0.001"
                      value={line.quantity}
                      onChange={(e) => setQty(line.id, Number(e.target.value))}
                    />
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-text2">
                    {KES(line.quantity * Number(line.cost_price || 0), currency)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Button size="sm" variant="ghost" onClick={() => toggle(line)}>Remove</Button>
                  </td>
                </tr>
              ))}
            </Table>
          </div>
          {!lines.length ? (
            <div className="p-8 text-center text-sm text-text2">
              Tick products in the list to add them here.
            </div>
          ) : null}
          <div className="flex items-center justify-between border-t border-border p-4">
            <div>
              <div className="text-xs text-text2">Total cost used</div>
              <div className="text-lg font-bold text-gold">{KES(total, currency)}</div>
              <div className="mt-1 text-xs text-text2">
                Retail opportunity {KES(retailValue, currency)} · foregone gross profit {KES(retailValue - total, currency)}
              </div>
            </div>
            <Button onClick={save} disabled={busy || !canCreate}>
              <PackageMinus className="h-4 w-4" /> Save Consumption
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function ConsumptionHistory({ currency, canVoid }: { currency: string; canVoid: boolean }) {
  const qc = useQueryClient();
  const [start, setStart] = useState(daysAgo(30));
  const [end, setEnd] = useState(todayISO());
  const [detailId, setDetailId] = useState<number | null>(null);
  const historyQ = useQuery({
    queryKey: ["consumptions", start, end],
    queryFn: () => GET<any[]>("/consumptions", { start, end, limit: "500" }),
  });
  const rows = Array.isArray(historyQ.data) ? historyQ.data : [];

  async function voidEntry(row: any) {
    const reason = window.prompt(`Why are you voiding ${row.reference_no}?`);
    if (!reason?.trim()) return;
    const pin = window.prompt("Enter the Super-Admin PIN");
    if (!pin) return;
    const result = await POST<any>(`/consumptions/${row.id}/void`, { reason, pin });
    if (!result?.success) {
      toast.error(result?.error || "Nothing was changed. Try again.");
      return;
    }
    toast.success(`${row.reference_no} voided · stock restored`);
    qc.invalidateQueries({ queryKey: ["consumptions"] });
    qc.invalidateQueries({ queryKey: ["products"] });
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border p-4">
        <div>
          <SectionTitle>Consumption history</SectionTitle>
          <p className="mt-1 text-xs text-text2">Open an entry to see every product used.</p>
        </div>
        <div className="flex gap-2">
          <label className="text-xs text-text2">From
            <Input className="mt-1" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="text-xs text-text2">To
            <Input className="mt-1" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
        </div>
      </div>
      <Table head={["Date", "Reference", "Department", "Reason", "Taken by", "Items", "Cost", "Status", ""]}>
        {rows.map((row) => (
          <tr
            key={row.id}
            className="cursor-pointer hover:bg-panel"
            tabIndex={0}
            onClick={() => setDetailId(Number(row.id))}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                setDetailId(Number(row.id));
              }
            }}
          >
            <td className="px-4 py-2.5 text-text2">{row.date}</td>
            <td className="px-4 py-2.5 font-mono text-xs text-text">{row.reference_no}</td>
            <td className="px-4 py-2.5 text-text">{row.department_name || "—"}</td>
            <td className="px-4 py-2.5 text-text2">{row.reason}</td>
            <td className="px-4 py-2.5 text-text2">{row.taken_by || "—"}</td>
            <td className="px-4 py-2.5 tabular-nums">{row.item_count}</td>
            <td className="px-4 py-2.5 font-semibold tabular-nums">{KES(row.total_cost, currency)}</td>
            <td className="px-4 py-2.5"><Badge tone={row.voided ? "err" : "ok"}>{row.voided ? "Voided" : "Posted"}</Badge></td>
            <td className="px-4 py-2.5">
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={(event) => {
                  event.stopPropagation();
                  setDetailId(Number(row.id));
                }}>
                  <Eye className="h-3.5 w-3.5" /> View
                </Button>
                {canVoid && !row.voided ? (
                  <Button size="sm" variant="ghost" onClick={(event) => {
                    event.stopPropagation();
                    void voidEntry(row);
                  }}>Void</Button>
                ) : null}
              </div>
            </td>
          </tr>
        ))}
      </Table>
      {!historyQ.isLoading && !rows.length ? (
        <div className="p-10 text-center text-sm text-text2">No consumption entries in this period.</div>
      ) : null}
      {detailId != null ? (
        <ConsumptionDetail id={detailId} currency={currency} onClose={() => setDetailId(null)} />
      ) : null}
    </Card>
  );
}

function ConsumptionDetail({ id, currency, onClose }: { id: number; currency: string; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["consumption-detail", id],
    queryFn: () => GET<any>(`/consumptions/${id}`),
  });
  const entry = q.data;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-border bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-text">{entry?.reference_no || "Consumption details"}</h3>
            <p className="text-sm text-text2">{entry?.department_name} · {entry?.reason}</p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
        </div>
        {entry ? (
          <>
            <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Value label="Buying cost used" value={KES(entry.total_buying_cost, currency)} />
              <Value label="Weighted avg buy / unit" value={KES(entry.average_buying_cost, currency)} />
              <Value label="Retail opportunity value" value={KES(entry.opportunity_value, currency)} accent />
              <Value label="Foregone gross profit" value={KES(entry.foregone_gross_profit, currency)} accent />
            </div>
            <div className="overflow-x-auto">
              <Table head={["Product", "Quantity", "Buy / unit", "Total buying", "Sell / unit", "Retail value"]}>
                {(entry.items || []).map((line: any) => (
                  <tr key={line.id}>
                    <td className="px-4 py-2.5 font-medium text-text">
                      {line.product_name}
                      <span className="block text-xs font-normal text-text2">
                        {[line.product_sku, line.product_unit].filter(Boolean).join(" · ")}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">{line.quantity} {line.product_unit || ""}</td>
                    <td className="px-4 py-2.5 tabular-nums">{KES(line.unit_cost, currency)}</td>
                    <td className="px-4 py-2.5 font-semibold tabular-nums">{KES(line.total_cost, currency)}</td>
                    <td className="px-4 py-2.5 tabular-nums">{KES(line.effective_selling_price, currency)}</td>
                    <td className="px-4 py-2.5 font-semibold tabular-nums text-gold">{KES(line.effective_selling_value, currency)}</td>
                  </tr>
                ))}
              </Table>
            </div>
            <p className="mt-3 text-xs text-text2">
              {entry.has_estimated_selling_prices
                ? "Some older entries predate price snapshots; their retail value uses the product’s current selling price."
                : "Retail Opportunity Value is what these quantities would have sold for at the prices captured when consumed."}
            </p>
          </>
        ) : <div className="p-8 text-center text-sm text-text2">Loading details…</div>}
      </div>
    </div>
  );
}

function Value({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-panel p-3">
      <div className="text-xs text-text2">{label}</div>
      <div className={`mt-1 text-base font-bold tabular-nums ${accent ? "text-gold" : "text-text"}`}>{value}</div>
    </div>
  );
}

function Departments({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["departments-all"],
    queryFn: () => GET<any[]>("/departments", { all: "1" }),
  });
  const rows = Array.isArray(q.data) ? q.data : [];
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<any | null>(null);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["departments-all"] });
    qc.invalidateQueries({ queryKey: ["departments-active"] });
  }

  async function save() {
    if (!name.trim()) {
      toast.error("Enter the department name");
      return;
    }
    const result = editing
      ? await PUT<any>(`/departments/${editing.id}`, { name: name.trim() })
      : await POST<any>("/departments", { name: name.trim() });
    if (!result?.success) {
      toast.error(result?.error || "The department was not saved. Nothing was changed.");
      return;
    }
    toast.success(result.message || "Department saved");
    setName("");
    setEditing(null);
    refresh();
  }

  async function archive(row: any) {
    if (!window.confirm(`Archive ${row.name}? Existing history will remain.`)) return;
    const result = await DEL<any>(`/departments/${row.id}`);
    if (!result?.success) {
      toast.error(result?.error || "The department was not archived. Nothing was changed.");
      return;
    }
    toast.success(result.message || "Department archived");
    refresh();
  }

  async function restore(row: any) {
    const result = await POST<any>(`/departments/${row.id}/restore`, {});
    if (!result?.success) {
      toast.error(result?.error || "The department was not restored. Nothing was changed.");
      return;
    }
    toast.success(result.message || "Department restored");
    refresh();
  }

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border p-4">
        <SectionTitle>Departments</SectionTitle>
        <p className="mt-1 text-xs text-text2">
          Archiving removes a department from new entries but keeps its history.
        </p>
        {canManage ? (
          <div className="mt-3 flex max-w-2xl gap-2">
            <Input
              className="min-h-[44px]"
              placeholder="Department name…"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void save(); }}
            />
            {editing ? <Button variant="ghost" onClick={() => { setEditing(null); setName(""); }}>Cancel</Button> : null}
            <Button onClick={() => void save()}><Plus className="h-4 w-4" /> {editing ? "Save name" : "Add"}</Button>
          </div>
        ) : null}
      </div>
      <Table head={["Department", "Status", "Entries", ...(canManage ? ["Actions"] : [])]}>
        {rows.map((row) => (
          <tr key={row.id}>
            <td className="px-4 py-2.5 font-medium text-text">{row.name}</td>
            <td className="px-4 py-2.5"><Badge tone={row.active ? "ok" : "muted"}>{row.active ? "Active" : "Archived"}</Badge></td>
            <td className="px-4 py-2.5 tabular-nums text-text2">{row.usage_count || 0}</td>
            {canManage ? (
              <td className="px-4 py-2.5">
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => { setEditing(row); setName(row.name); }}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
                  {row.active ? (
                    <Button size="sm" variant="ghost" onClick={() => void archive(row)}><Archive className="h-3.5 w-3.5" /> Archive</Button>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => void restore(row)}><RotateCcw className="h-3.5 w-3.5" /> Restore</Button>
                  )}
                </div>
              </td>
            ) : null}
          </tr>
        ))}
      </Table>
    </Card>
  );
}
