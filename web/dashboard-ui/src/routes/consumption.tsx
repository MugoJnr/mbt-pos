import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { downloadApi } from "@/lib/download";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/consumption")({
  component: ConsumptionPage,
});

const REASONS = ["Cleaning", "Staff Consumption", "Office Use", "Production", "Damaged During Production", "Other"];

function localToday() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function ConsumptionPage() {
  const qc = useQueryClient();
  const today = localToday();
  const [departmentId, setDepartmentId] = useState("");
  const [newDepartment, setNewDepartment] = useState("");
  const [productQuery, setProductQuery] = useState("");
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [lines, setLines] = useState<{ id: number; name: string; sku: string; quantity: number; stock: number }[]>([]);
  const [reason, setReason] = useState("Cleaning");
  const [notes, setNotes] = useState("");
  const [takenBy, setTakenBy] = useState("");
  const [when, setWhen] = useState(today);
  const [error, setError] = useState("");
  const [voidReason, setVoidReason] = useState("");
  const [savedRef, setSavedRef] = useState("");
  const tokenRef = useRef("");
  const [reportStart, setReportStart] = useState(today);
  const [reportEnd, setReportEnd] = useState(today);
  const [reportReason, setReportReason] = useState("");
  const [report, setReport] = useState<{ rows: any[]; totals: any } | null>(null);
  const [reportError, setReportError] = useState("");

  const departmentsQ = useQuery({
    queryKey: ["departments"],
    queryFn: () => GET<any[]>("/departments"),
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<any[]>("/products"),
  });
  const listQ = useQuery({
    queryKey: ["consumptions", today],
    queryFn: () => GET<any[]>("/consumptions", { start: "2020-01-01", end: today }),
  });

  const departments = Array.isArray(departmentsQ.data) ? departmentsQ.data : [];
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
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
    return name.includes(query) || sku.includes(query);
  });
  const product = visibleProducts.find((p) => String(p.id) === productId) || null;
  const available = Number(product?.stock || 0);
  const unitCost = Number(product?.cost_price || 0);

  function addLine() {
    setError("");
    const amount = Number(qty);
    if (!product) return setError("Choose a product from the list.");
    if (!Number.isFinite(amount) || amount <= 0) return setError("Quantity must be greater than zero.");
    if (amount > available) return setError(`Only ${available} available for ${product.name}.`);
    if (lines.some((line) => line.id === Number(product.id))) {
      return setError("That product is already on this consumption.");
    }
    setLines((current) => [
      ...current,
      {
        id: Number(product.id),
        name: String(product.name || ""),
        sku: String(product.sku || ""),
        quantity: amount,
        stock: available,
      },
    ]);
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
    if (reportReason) params.set("reason", reportReason);
    const res = await GET<any>(`/consumptions/report?${params.toString()}`);
    if (!res || res.error || !Array.isArray(res.rows)) {
      setReport(null);
      setReportError(res?.error || "Could not load the report.");
      return;
    }
    setReport(res);
  }

  async function exportReport() {
    setReportError("");
    const params = new URLSearchParams({ start: reportStart, end: reportEnd });
    if (reportReason) params.set("reason", reportReason);
    try {
      await downloadApi(`/consumptions/report/export?${params.toString()}`, `consumption-${reportStart}.xlsx`);
    } catch (err) {
      setReportError(err instanceof Error ? err.message : "Could not export the report.");
    }
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
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["products"] });
  }

  return (
    <AppShell title="Internal Consumption">
      <PageHeader
        eyebrow="Operations"
        title="Internal Consumption"
        description="Stock used by the shop. This is not a sale and does not create a customer debt."
      />
      <Card padded className="mb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="text-sm text-text2">
            Department
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text"
              value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value)}
            >
              <option value="">Select</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-text2">
            New department
            <div className="mt-1 flex gap-2">
              <Input value={newDepartment} onChange={(e) => setNewDepartment(e.target.value)} placeholder="Office" />
              <Button onClick={createDepartment}>Add</Button>
            </div>
          </label>
          <label className="text-sm text-text2 md:col-span-2">
            Find product
            <Input
              className="mt-1"
              value={productQuery}
              onChange={(e) => setProductQuery(e.target.value)}
              placeholder="Name or SKU"
            />
          </label>
          <label className="text-sm text-text2 md:col-span-2">
            Product
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
            >
              <option value="">{visibleProducts.length ? "Select" : "No matching products"}</option>
              {visibleProducts.map((p) => (
                <option key={p.id} value={p.id}>{p.name} · {p.sku || "no sku"} · stock {p.stock}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-text2">
            Quantity
            <Input value={qty} onChange={(e) => setQty(e.target.value)} />
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
          <label className="text-sm text-text2 md:col-span-2">
            Notes
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
          </label>
        </div>
        <p className="mt-3 text-sm text-text2">
          Available {available}. Estimated cost {KES(unitCost * (Number(qty) || 0))} from purchase cost, not the selling price.
        </p>
        <div className="mt-3">
          <Button onClick={addLine}>Add product</Button>
        </div>
        {lines.length ? (
          <ul className="mt-3 space-y-1 text-sm">
            {lines.map((line) => (
              <li key={line.id} className="flex items-center justify-between gap-2">
                <span>{line.name} · {line.sku || "no sku"} · qty {line.quantity}</span>
                <Button onClick={() => setLines((current) => current.filter((item) => item.id !== line.id))}>Remove</Button>
              </li>
            ))}
          </ul>
        ) : null}
        {savedRef ? <p className="mt-2 text-sm text-ok">Saved {savedRef}. Stock has been reduced.</p> : null}
        {loadError ? <p className="mt-2 text-sm text-err">{loadError}</p> : null}
        {error ? <p className="mt-2 text-sm text-err">{error}</p> : null}
        <div className="mt-3">
          <Button onClick={save}>Record consumption</Button>
        </div>
      </Card>
      <Card>
        <div className="p-4 border-b border-border flex items-center gap-3">
          <Input
            value={voidReason}
            onChange={(e) => setVoidReason(e.target.value)}
            placeholder="Reason required before void"
          />
        </div>
        <Table head={["Ref", "Date", "Department", "Reason", "Cost", "Status", ""]}>
          {rows.slice(0, 40).map((row) => (
            <tr key={row.id}>
              <td className="px-4 py-2.5 font-mono text-sm">{row.reference_no}</td>
              <td className="px-4 py-2.5">{row.date}</td>
              <td className="px-4 py-2.5">{row.department_name || row.department_id}</td>
              <td className="px-4 py-2.5">{row.reason}</td>
              <td className="px-4 py-2.5 tabular-nums">{KES(row.total_cost || 0)}</td>
              <td className="px-4 py-2.5">
                <Badge tone={row.voided ? "err" : "ok"}>{row.voided ? "voided" : "posted"}</Badge>
              </td>
              <td className="px-4 py-2.5">
                {row.voided ? null : (
                  <Button onClick={() => reverse(row.id)}>Void</Button>
                )}
              </td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card padded className="mt-4">
        <h2 className="text-lg font-semibold">Consumption report</h2>
        <p className="mt-1 text-sm text-text2">Line totals for the selected dates. Voided lines stay visible and are included in the total.</p>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="text-sm text-text2">From
            <Input className="mt-1" type="date" value={reportStart} onChange={(e) => setReportStart(e.target.value)} />
          </label>
          <label className="text-sm text-text2">To
            <Input className="mt-1" type="date" value={reportEnd} onChange={(e) => setReportEnd(e.target.value)} />
          </label>
          <label className="text-sm text-text2">Reason
            <select className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text" value={reportReason} onChange={(e) => setReportReason(e.target.value)}>
              <option value="">All reasons</option>
              {REASONS.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <div className="flex items-end gap-2">
            <Button onClick={runReport}>Run report</Button>
            <Button onClick={exportReport}>Export Excel</Button>
          </div>
        </div>
        {reportError ? <p className="mt-2 text-sm text-err">{reportError}</p> : null}
        {report ? (
          <>
            <p className="mt-3 text-sm">
              {report.totals?.line_count || 0} lines · {report.totals?.consumption_count || 0} consumptions · Qty {report.totals?.total_qty || 0} · Total {KES(report.totals?.total_cost || 0)}
            </p>
            <div className="mt-2">
              <Table head={["Date", "Reference", "Product", "Qty", "Cost", "Status"]}>
                {(report.rows || []).map((row, index) => (
                  <tr key={`${row.consumption_id}-${row.product_id}-${index}`}>
                    <td className="px-4 py-2.5">{String(row.date || "").slice(0, 10)}</td>
                    <td className="px-4 py-2.5 font-mono text-sm">{row.reference_no}</td>
                    <td className="px-4 py-2.5">{row.product_name}</td>
                    <td className="px-4 py-2.5 tabular-nums">{row.quantity}</td>
                    <td className="px-4 py-2.5 tabular-nums">{KES(row.total_cost || 0)}</td>
                    <td className="px-4 py-2.5">{row.voided ? "Voided" : "OK"}</td>
                  </tr>
                ))}
              </Table>
            </div>
          </>
        ) : null}
      </Card>
    </AppShell>
  );
}
