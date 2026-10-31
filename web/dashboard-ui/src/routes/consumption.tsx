import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApiPost } from "@/lib/download";
import { ExportLockDialog } from "@/components/export-lock-dialog";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/consumption")({
  component: ConsumptionPage,
});

const REASONS = [
  "Production",
  "Staff Consumption",
  "Office Use",
  "Cleaning",
  "Sampling",
  "Damaged During Production",
  "Donation",
  "Promotion",
  "Other",
];

function localToday() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function ConsumptionPage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || "");
  const canRecord = ["cashier", "manager", "admin", "superadmin"].includes(role);
  const canVoid = ["admin", "superadmin"].includes(role);
  const canEdit = ["admin", "superadmin"].includes(role);
  const canRequestVoid = ["cashier", "manager"].includes(role);
  const [pane, setPane] = useState<"record" | "history" | "report">(canRecord ? "record" : "history");
  const [viewId, setViewId] = useState<number | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editLines, setEditLines] = useState<{ id: number; name: string; sku: string; quantity: string; stock: number; unit: string }[]>([]);
  const [editReason, setEditReason] = useState("");
  const [editCategory, setEditCategory] = useState("Cleaning");
  const today = localToday();
  const [departmentId, setDepartmentId] = useState("");
  const [newDepartment, setNewDepartment] = useState("");
  const [productQuery, setProductQuery] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [lines, setLines] = useState<{ id: number; name: string; sku: string; quantity: number; stock: number; unitCost: number; unit: string }[]>([]);
  const [reason, setReason] = useState("Cleaning");
  const [notes, setNotes] = useState("");
  const [takenBy, setTakenBy] = useState("");
  const [when, setWhen] = useState(today);
  const [error, setError] = useState("");
  const [voidReason, setVoidReason] = useState("");
  const [savedRef, setSavedRef] = useState("");
  const tokenRef = useRef("");
  const [histStart, setHistStart] = useState(today);
  const [histEnd, setHistEnd] = useState(today);
  const [histDept, setHistDept] = useState("");
  const [histReason, setHistReason] = useState("");
  const [reportStart, setReportStart] = useState(today);
  const [reportEnd, setReportEnd] = useState(today);
  const [reportDept, setReportDept] = useState("");
  const [reportReason, setReportReason] = useState("");
  const [report, setReport] = useState<{ rows: any[]; totals: any } | null>(null);
  const [reportError, setReportError] = useState("");
  const [consLock, setConsLock] = useState(false);
  const [consBusy, setConsBusy] = useState(false);

  const departmentsQ = useQuery({
    queryKey: ["departments"],
    queryFn: () => GET<any[]>("/departments"),
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<any[]>("/products"),
  });
  const listQ = useQuery({
    queryKey: ["consumptions", histStart, histEnd, histDept, histReason],
    queryFn: () => GET<any[]>("/consumptions", {
      start: histStart,
      end: histEnd,
      ...(histDept ? { department_id: histDept } : {}),
      ...(histReason ? { reason: histReason } : {}),
    }),
  });

  const departments = Array.isArray(departmentsQ.data) ? departmentsQ.data : [];
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const viewQ = useQuery({
    queryKey: ["consumption", viewId],
    enabled: viewId != null,
    queryFn: () => GET<any>(`/consumptions/${viewId}`),
  });
  const rows = Array.isArray(listQ.data) ? listQ.data : [];
  const loadError = String(
    (!Array.isArray(departmentsQ.data) && (departmentsQ.data as { error?: string } | undefined)?.error)
    || (!Array.isArray(listQ.data) && (listQ.data as { error?: string } | undefined)?.error)
    || "",
  );
  const query = productQuery.trim().toLowerCase();
  const visibleProducts = products.filter((p) => {
    if (!query) return true;
    const name = String(p.name || "").toLowerCase();
    const sku = String(p.sku || "").toLowerCase();
    const barcode = String(p.barcode || "").toLowerCase();
    return name.includes(query) || sku.includes(query) || barcode.includes(query);
  });
  const product = visibleProducts.find((p) => String(p.id) === productId) || null;
  const available = Number(product?.stock || 0);
  const unitCost = Number(product?.cost_price || 0);

  function addLine(chosen?: any) {
    setError("");
    const picked = chosen && typeof chosen.id !== "undefined" && chosen.name ? chosen : product;
    const amount = Number(qty);
    if (!picked) return setError("Choose a product from the list.");
    if (!Number.isFinite(amount) || amount <= 0) return setError("Quantity must be greater than zero.");
    const pickedStock = Number(picked.stock || 0);
    const pickedCost = Number(picked.cost_price || 0);
    if (amount > pickedStock) return setError(`Only ${pickedStock} available for ${picked.name}.`);
    if (lines.some((line) => line.id === Number(picked.id))) {
      return setError("That product is already on this consumption.");
    }
    setLines((current) => [
      ...current,
      {
        id: Number(picked.id),
        name: String(picked.name || ""),
        sku: String(picked.sku || ""),
        quantity: amount,
        stock: pickedStock,
        unitCost: pickedCost,
        unit: String(picked.unit || "pcs"),
      },
    ]);
    setProductId(String(picked.id));
    setQty("1");
  }

  async function createDepartment() {
    setError("");
    const name = newDepartment.trim();
    if (!name) return setError("Enter a department name.");
    const res = await POST<any>("/departments", { name });
    if (!res || res.error) return setError(res?.error || "Could not save the department.");
    setDepartmentId(String(res.id));
    setNewDepartment("");
    await qc.invalidateQueries({ queryKey: ["departments"] });
  }

  async function save() {
    setError("");
    setSavedRef("");
    if (!departmentId) return setError("Choose a department.");
    if (!lines.length) return setError("Add at least one product.");
    if (when > today) return setError("Future dates are not allowed.");
    if (!tokenRef.current) tokenRef.current = crypto.randomUUID();
    const res = await POST<any>("/consumptions", {
      department_id: Number(departmentId),
      reason,
      notes,
      taken_by: takenBy,
      date: when,
      client_token: tokenRef.current,
      items: lines.map((line) => ({ product_id: line.id, quantity: line.quantity })),
    });
    if (!res || res.error) {
      setError(res?.error || "Could not save consumption.");
      return;
    }
    tokenRef.current = "";
    setSavedRef(String(res.reference_no || ""));
    setNotes("");
    setQty("1");
    setLines([]);
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["products"] });
  }

  async function runReport() {
    setReportError("");
    const params = new URLSearchParams({ start: reportStart, end: reportEnd });
    if (reportDept) params.set("department_id", reportDept);
    if (reportReason) params.set("reason", reportReason);
    const res = await GET<any>(`/consumptions/report?${params.toString()}`);
    if (!res || res.error || !Array.isArray(res.rows)) {
      setReport(null);
      setReportError(res?.error || "Could not load the report.");
      return;
    }
    setReport(res);
  }

  async function exportReport(password: string) {
    setReportError("");
    setConsBusy(true);
    try {
      const qs = new URLSearchParams({ start: reportStart, end: reportEnd });
      if (reportDept) qs.set("department_id", reportDept);
      if (reportReason) qs.set("reason", reportReason);
      await downloadApiPost(
        `/consumptions/report/export?${qs.toString()}`,
        { password, confirm: password },
        `consumption-${reportStart}.xlsx`,
      );
      setConsLock(false);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Could not export the report.");
    } finally {
      setConsBusy(false);
    }
  }

  async function requestVoid(id: number) {
    setError("");
    const why = voidReason.trim();
    if (!why) return setError("Enter a void reason first. Stock stays reduced until an admin approves.");
    const res = await POST<any>(`/consumptions/${id}/void-request`, { reason: why });
    if (!res || res.error) {
      setError(res?.error || "Could not send the void request.");
      return;
    }
    setError("");
    setSavedRef(res.duplicate ? "That void is already waiting for an admin." : "Void request sent. Stock has not been restored.");
    setViewId(null);
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["consumption"] });
  }

  async function openEdit(id: number) {
    setError("");
    const detail = await GET<any>(`/consumptions/${id}`);
    if (!detail || detail.error) {
      setError(detail?.error || "Could not open that consumption.");
      return;
    }
    if (Number(detail.voided || 0) === 1) {
      setError("A voided consumption cannot be edited.");
      return;
    }
    setEditId(id);
    setEditCategory(String(detail.reason || "Other"));
    setEditReason("");
    setEditLines((detail.items || []).map((item: any) => ({
      id: Number(item.product_id),
      name: String(item.product_name || ""),
      sku: String(item.sku || ""),
      quantity: String(item.quantity ?? ""),
      stock: Number(item.stock || 0) + Number(item.quantity || 0),
      unit: String(item.unit || "pcs"),
    })));
  }

  async function saveEdit() {
    setError("");
    if (!editId) return;
    if (editReason.trim().length < 3) return setError("Enter why this consumption is being corrected.");
    const items = editLines.map((line) => ({
      product_id: line.id,
      quantity: Number(line.quantity),
    })).filter((line) => line.quantity > 0);
    if (!items.length) return setError("Keep at least one product, or void the consumption.");
    const res = await PUT<any>(`/consumptions/${editId}`, {
      edit_reason: editReason.trim(),
      reason: editCategory,
      items,
      client_token: crypto.randomUUID(),
    });
    if (!res || res.error) return setError(res?.error || "Could not save the correction.");
    setSavedRef(`${res.reference_no} corrected. Only the quantity difference was applied.`);
    setEditId(null);
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["products"] });
    await qc.invalidateQueries({ queryKey: ["consumption"] });
  }

  async function reverse(id: number) {
    setError("");
    const why = voidReason.trim();
    if (!why) return setError("Enter a void reason first.");
    const res = await POST<any>(`/consumptions/${id}/void`, { reason: why });
    if (!res || res.error) {
      setError(res?.error || "Could not void that consumption.");
      return;
    }
    setViewId(null);
    setSavedRef("Voided. Stock has been restored.");
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["products"] });
    await qc.invalidateQueries({ queryKey: ["consumption"] });
  }

  return (
    <AppShell title="Internal Consumption">
      <ExportLockDialog
        open={consLock}
        kind="Excel workbook"
        busy={consBusy}
        error={reportError}
        onCancel={() => {
          if (!consBusy) setConsLock(false);
        }}
        onConfirm={(password) => {
          void exportReport(password);
        }}
      />
      <PageHeader
        eyebrow="Operations"
        title="Internal Consumption"
        description="Stock used by the shop. This is not a sale and does not create a customer debt. Open History or Report and click a row to see the receipt, void it, or request a void."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {canRecord ? <Button variant={pane === "record" ? "primary" : "secondary"} onClick={() => setPane("record")}>New consumption</Button> : null}
        <Button variant={pane === "history" ? "primary" : "secondary"} onClick={() => setPane("history")}>History</Button>
        <Button variant={pane === "report" ? "primary" : "secondary"} onClick={() => setPane("report")}>Report</Button>
      </div>
      {canRecord && pane === "record" ? (
      <Card padded className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="text-sm text-text2 md:col-span-3">
            Department
            <div className="mt-1 grid grid-cols-1 gap-2 md:grid-cols-[1fr_16rem_auto]">
              <select
                aria-label="Department"
                className="h-10 w-full rounded-md border border-border bg-panel px-3 text-text"
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
              >
                <option value="">Select department</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
              <Input
                aria-label="New department"
                value={newDepartment}
                onChange={(e) => setNewDepartment(e.target.value)}
                placeholder="New department name"
              />
              <Button onClick={createDepartment}>Add department</Button>
            </div>
          </label>
          <label className="text-sm text-text2 md:col-span-2">
            Find product
            <Input
              className="mt-1"
              value={productQuery}
              onChange={(e) => setProductQuery(e.target.value)}
              placeholder="Name, SKU, or barcode"
            />
          </label>
          <label className="text-sm text-text2">
            Quantity
            <Input className="mt-1" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="0.25" />
          </label>
          <label className="text-sm text-text2">
            Reason
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              {REASONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-text2">
            Business date
            <Input type="date" max={today} value={when} onChange={(e) => setWhen(e.target.value)} />
          </label>
          <label className="text-sm text-text2">
            Taken by
            <Input value={takenBy} onChange={(e) => setTakenBy(e.target.value)} placeholder="Name" />
          </label>
          <label className="text-sm text-text2 md:col-span-3">
            Notes
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
          </label>
        </div>
        <div className="mt-3 min-h-[280px] max-h-[420px] overflow-auto rounded-lg border border-border">
          <div className="sticky top-0 grid grid-cols-[1fr_auto_auto_auto] gap-3 border-b border-border bg-panel px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
            <span>Product</span><span>SKU</span><span className="text-right">Unit</span><span className="text-right">Stock</span>
          </div>
          {visibleProducts.slice(0, 80).map((p) => (
            <button
              key={p.id}
              type="button"
              className={`grid w-full grid-cols-[1fr_auto_auto_auto] gap-3 border-b border-border px-3 py-2 text-left text-sm last:border-0 hover:bg-hover ${String(p.id) === productId ? "bg-hover" : ""}`}
              onClick={() => setProductId(String(p.id))}
              onDoubleClick={() => addLine(p)}
            >
              <span className="font-medium text-text">{p.name}</span>
              <span className="text-text2">{p.sku || "—"}</span>
              <span className="text-right">{p.unit || "pcs"}</span>
              <span className="text-right tabular-nums">{p.stock}</span>
            </button>
          ))}
          {!visibleProducts.length ? <p className="px-3 py-6 text-sm text-text2">No matching products.</p> : null}
        </div>
        <p className="mt-3 text-sm text-text2">
          {product ? `${product.name} · ${available} ${product.unit || "pcs"} available · estimated ${KES(unitCost * (Number(qty) || 0))} from purchase cost` : "Select a product, enter a quantity such as 0.25, then add it. Earlier lines stay on the list."}
        </p>
        <div className="mt-3">
          <Button onClick={addLine}>Add product</Button>
        </div>
        {lines.length ? (
          <div className="mt-3 overflow-hidden rounded-lg border border-border">
            <div className="grid grid-cols-[1fr_auto_8rem_auto_auto] gap-3 border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
              <span>Product</span><span className="text-right">Stock</span><span className="text-right">Qty</span><span className="text-right">Line cost</span><span />
            </div>
            {lines.map((line) => (
              <div key={line.id} className="grid grid-cols-[1fr_auto_8rem_auto_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0">
                <div>
                  <div className="font-medium text-text">{line.name}</div>
                  <div className="text-xs text-text2">{line.sku || "No SKU"} · {line.unit || "pcs"} · {KES(line.unitCost)} each</div>
                </div>
                <div className="text-right tabular-nums text-text2">{line.stock}</div>
                <Input
                  className="text-right"
                  inputMode="decimal"
                  value={String(line.quantity)}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (!Number.isFinite(next)) return;
                    setLines((current) => current.map((item) => item.id === line.id ? { ...item, quantity: next } : item));
                  }}
                />
                <div className="text-right font-semibold tabular-nums text-gold">{KES(line.unitCost * line.quantity)}</div>
                <Button variant="ghost" onClick={() => setLines((current) => current.filter((item) => item.id !== line.id))}>Remove</Button>
              </div>
            ))}
          </div>
        ) : null}
        {lines.length ? (
          <div className="mt-3 flex items-center justify-between rounded-lg border border-border bg-panel px-4 py-3">
            <span className="text-sm text-text2">Estimated stock cost</span>
            <span className="text-xl font-extrabold tabular-nums text-gold">{KES(lines.reduce((sum, line) => sum + line.unitCost * line.quantity, 0))}</span>
          </div>
        ) : null}
        {savedRef ? (
          <p className="mt-2 text-sm text-ok">
            {/^(AUTO-|INV-|RCP-)/.test(savedRef) || savedRef.includes("corrected")
              ? (savedRef.includes("corrected") ? `Saved ${savedRef}` : `Saved ${savedRef}. Stock has been reduced.`)
              : savedRef}
          </p>
        ) : null}
        {loadError ? <p className="mt-2 text-sm text-err">{loadError}</p> : null}
        {error ? <p className="mt-2 text-sm text-err">{error}</p> : null}
        <div className="mt-3">
          <Button onClick={save}>Record consumption</Button>
        </div>
      </Card>
      ) : null}
      {pane === "history" ? (
      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
          <label className="text-sm text-text2">From
            <Input className="mt-1" type="date" value={histStart} onChange={(e) => setHistStart(e.target.value)} />
          </label>
          <label className="text-sm text-text2">To
            <Input className="mt-1" type="date" value={histEnd} onChange={(e) => setHistEnd(e.target.value)} />
          </label>
          <label className="text-sm text-text2">Department
            <select aria-label="History department" className="mt-1 h-10 rounded-md border border-border bg-panel px-3 text-text" value={histDept} onChange={(e) => setHistDept(e.target.value)}>
              <option value="">All departments</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <label className="text-sm text-text2">Reason
            <select aria-label="History reason" className="mt-1 h-10 rounded-md border border-border bg-panel px-3 text-text" value={histReason} onChange={(e) => setHistReason(e.target.value)}>
              <option value="">All reasons</option>
              {REASONS.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <Button variant="secondary" onClick={() => { setHistStart(today); setHistEnd(today); setHistDept(""); setHistReason(""); }}>Today</Button>
          <p className="pb-2 text-sm text-text2">Click a row to open the receipt. Void, request void, and edit are on that receipt.</p>
        </div>
        {savedRef && pane === "history" ? <p className="px-4 pt-3 text-sm text-ok">{savedRef}</p> : null}
        {error && pane === "history" ? <p className="px-4 pt-3 text-sm text-err">{error}</p> : null}
        <Table head={["Reference", "Date", "Department", "Reason", "Cost", "Status"]}>
          {rows.slice(0, 80).map((row) => (
            <tr key={row.id} className="cursor-pointer hover:bg-hover" onClick={() => setViewId(row.id)}>
              <td className="px-4 py-2.5 font-mono text-sm">{row.reference_no}</td>
              <td className="px-4 py-2.5">{String(row.date || "").slice(0, 10)}</td>
              <td className="px-4 py-2.5">{row.department_name || "—"}</td>
              <td className="px-4 py-2.5">{row.reason}</td>
              <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-gold">{KES(row.total_cost || 0)}</td>
              <td className="px-4 py-2.5">
                <Badge tone={row.voided ? "err" : row.void_requested ? "warn" : "ok"}>
                  {row.voided ? "Voided" : row.void_requested ? "Requested" : "Posted"}
                </Badge>
              </td>
            </tr>
          ))}
        </Table>
      </Card>
      ) : null}
      {pane === "report" ? (
      <Card padded>
        <h2 className="text-lg font-semibold">Consumption report</h2>
        <p className="mt-1 text-sm text-text2">Click a line to open that consumption receipt. Voided lines stay visible and are marked.</p>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-5 gap-3">
          <label className="text-sm text-text2">From
            <Input className="mt-1" type="date" value={reportStart} onChange={(e) => setReportStart(e.target.value)} />
          </label>
          <label className="text-sm text-text2">To
            <Input className="mt-1" type="date" value={reportEnd} onChange={(e) => setReportEnd(e.target.value)} />
          </label>
          <label className="text-sm text-text2">Department
            <select aria-label="Report department" className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text" value={reportDept} onChange={(e) => setReportDept(e.target.value)}>
              <option value="">All departments</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <label className="text-sm text-text2">Reason
            <select className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text" value={reportReason} onChange={(e) => setReportReason(e.target.value)}>
              <option value="">All reasons</option>
              {REASONS.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <div className="flex items-end gap-2">
            <Button onClick={runReport}>Run report</Button>
            <Button onClick={() => setConsLock(true)}>Export Excel</Button>
          </div>
        </div>
        {reportError ? <p className="mt-2 text-sm text-err">{reportError}</p> : null}
        {report ? (
          <>
            <p className="mt-3 text-sm">
              {report.totals?.line_count || 0} lines · {report.totals?.consumption_count || 0} consumptions · Qty {report.totals?.total_qty || 0} · Posted cost {KES((report.rows || []).filter((row) => !row.voided).reduce((sum, row) => sum + Number(row.total_cost || 0), 0))} · Including voided {KES(report.totals?.total_cost || 0)}
            </p>
            <div className="mt-2">
              <Table head={["Date", "Reference", "Product", "Qty", "Cost", "Status"]}>
                {(report.rows || []).map((row, index) => (
                  <tr
                    key={`${row.consumption_id}-${row.product_id}-${index}`}
                    className="cursor-pointer hover:bg-hover"
                    onClick={() => setViewId(Number(row.consumption_id))}
                  >
                    <td className="px-4 py-2.5">{String(row.date || "").slice(0, 10)}</td>
                    <td className="px-4 py-2.5 font-mono text-sm">{row.reference_no}</td>
                    <td className="px-4 py-2.5">
                      <div>{row.product_name}</div>
                      <div className="text-xs text-text2">{row.department_name || "—"} · {row.reason || "—"}</div>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">{row.quantity}</td>
                    <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-gold">{KES(row.total_cost || 0)}</td>
                    <td className="px-4 py-2.5">{row.voided ? "Voided" : "Posted"}</td>
                  </tr>
                ))}
              </Table>
            </div>
          </>
        ) : null}
      </Card>
      ) : null}
      {viewId != null ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setViewId(null)}>
          <div className="w-full max-w-lg" onClick={(event) => event.stopPropagation()}>
          <Card className="max-h-[80vh] overflow-auto p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-gold">Internal consumption</div>
            <div className="mt-1 text-lg font-extrabold">{viewQ.data?.reference_no || "Receipt"}</div>
            <p className="mt-2 text-sm text-text2">Stock used by the business. This is not a customer sale and has no payment.</p>
            {viewQ.isLoading ? <p className="mt-3 text-sm">Loading…</p> : null}
            {viewQ.data?.error ? <p className="mt-3 text-sm text-err">{viewQ.data.error}</p> : null}
            {viewQ.data && !viewQ.data.error ? (
              <div className="mt-3 space-y-3 text-sm">
                <div className="text-text2">
                  {Number(viewQ.data.voided || 0) === 1 ? "Voided" : viewQ.data.void_requested ? "Void requested" : "Posted"}
                  {" · "}{String(viewQ.data.created_at || viewQ.data.date || "").replace("T", " ").slice(0, 19)}
                  {" · "}{viewQ.data.created_by_name || "—"} · {viewQ.data.department_name || "—"}
                </div>
                <div>Taken by {viewQ.data.taken_by || "—"} · {viewQ.data.reason || "—"}</div>
                {viewQ.data.notes ? <div>Notes {viewQ.data.notes}</div> : null}
                <div className="overflow-x-auto rounded-lg border border-border">
                  <div className="grid min-w-[720px] grid-cols-[1.4fr_auto_auto_auto_auto_auto_auto] gap-3 border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
                    <span>Product</span><span className="text-right">Qty</span><span className="text-right">Unit</span><span className="text-right">Unit cost</span><span className="text-right">Line</span><span className="text-right">Before</span><span className="text-right">After</span>
                  </div>
                  {(viewQ.data.items || []).map((item: any) => (
                    <div key={item.id} className="grid min-w-[720px] grid-cols-[1.4fr_auto_auto_auto_auto_auto_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0">
                      <div>
                        <div className="font-medium text-text">{item.product_name}</div>
                        <div className="text-xs text-text2">{item.sku || "No SKU"}</div>
                      </div>
                      <div className="text-right tabular-nums">{item.quantity}</div>
                      <div className="text-right">{item.unit || "pcs"}</div>
                      <div className="text-right tabular-nums">{KES(item.unit_cost || 0)}</div>
                      <div className="text-right font-semibold tabular-nums text-gold">{KES(item.total_cost || 0)}</div>
                      <div className="text-right tabular-nums">{item.stock_before ?? "—"}</div>
                      <div className="text-right tabular-nums">{item.stock_after ?? "—"}</div>
                    </div>
                  ))}
                </div>
                <div className="text-sm text-text2">
                  {(viewQ.data.items || []).length} products
                  {" · "}
                  {Object.entries(((viewQ.data.items || []) as any[]).reduce((groups: Record<string, number>, item: any) => {
                    const unit = String(item.unit || "pcs");
                    groups[unit] = (groups[unit] || 0) + Number(item.quantity || 0);
                    return groups;
                  }, {})).map(([unit, amount]) => `${amount} ${unit}`).join(" · ") || "—"}
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border bg-panel px-4 py-3">
                  <span className="text-text2">Stock cost</span>
                  <span className="text-xl font-extrabold tabular-nums text-gold">{KES(viewQ.data.total_cost || 0)}</span>
                </div>
                {error ? <p className="text-sm text-err">{error}</p> : null}
                {Number(viewQ.data.voided || 0) !== 1 ? (
                  <Input value={voidReason} onChange={(e) => setVoidReason(e.target.value)} placeholder="Reason, required before void or request void" aria-label="Void reason" />
                ) : null}
                <div className="flex flex-wrap justify-end gap-2">
                  {canEdit && !viewQ.data.voided ? <Button variant="secondary" onClick={() => { const id = viewId; setViewId(null); if (id) void openEdit(id); }}>Edit</Button> : null}
                  {canVoid && !viewQ.data.voided ? <Button variant="danger" onClick={() => { if (viewId) void reverse(viewId); }}>Void</Button> : null}
                  {canRequestVoid && !viewQ.data.voided ? (
                    <Button variant="secondary" disabled={Boolean(viewQ.data.void_requested)} onClick={() => { if (viewId) void requestVoid(viewId); }}>
                      {viewQ.data.void_requested ? "Void requested" : "Request void"}
                    </Button>
                  ) : null}
                  <Button variant="ghost" onClick={() => setViewId(null)}>Close</Button>
                </div>
              </div>
            ) : null}
          </Card>
          </div>
        </div>
      ) : null}
      {editId != null ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
          <Card className="max-h-[80vh] w-full max-w-lg overflow-auto p-5">
            <div className="text-lg font-extrabold">Correct consumption</div>
            <p className="mt-1 text-sm text-text2">Only the difference in quantity changes stock. The original lines stay in the correction history.</p>
            <div className="mt-3 space-y-2">
              {editLines.map((line) => (
                <div key={line.id} className="flex items-center gap-2 text-sm">
                  <span className="flex-1">{line.name} · {line.unit} · on hand before this line {line.stock}</span>
                  <Input className="w-24" value={line.quantity} onChange={(event) => setEditLines((current) => current.map((item) => item.id === line.id ? { ...item, quantity: event.target.value } : item))} />
                  <Button onClick={() => setEditLines((current) => current.filter((item) => item.id !== line.id))}>Remove</Button>
                </div>
              ))}
            </div>
            <label className="mt-3 block text-sm text-text2">Reason
              <select className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2" value={editCategory} onChange={(event) => setEditCategory(event.target.value)}>
                {REASONS.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label className="mt-3 block text-sm text-text2">Why this correction
              <Input className="mt-1" value={editReason} onChange={(event) => setEditReason(event.target.value)} placeholder="Required" />
            </label>
            <div className="mt-3 flex gap-2">
              <Button onClick={saveEdit}>Save correction</Button>
              <Button onClick={() => setEditId(null)}>Cancel</Button>
            </div>
          </Card>
        </div>
      ) : null}
    </AppShell>
  );
}
