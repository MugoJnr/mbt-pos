import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/consumption")({
  component: ConsumptionPage,
});

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
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState("1");
  const [reason, setReason] = useState("Cleaning");
  const [notes, setNotes] = useState("");
  const [takenBy, setTakenBy] = useState("");
  const [when, setWhen] = useState(today);
  const [error, setError] = useState("");
  const [voidReason, setVoidReason] = useState("");

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
  const product = products.find((p) => String(p.id) === productId);
  const available = Number(product?.stock || 0);
  const unitCost = Number(product?.cost_price || 0);

  async function save() {
    setError("");
    const amount = Number(qty);
    if (!departmentId) return setError("Choose a department.");
    if (!productId) return setError("Choose a product.");
    if (!Number.isFinite(amount) || amount <= 0) return setError("Quantity must be greater than zero.");
    if (amount > available) return setError(`Only ${available} available.`);
    if (when > today) return setError("Future dates are not allowed.");
    const res = await POST<any>("/consumptions", {
      department_id: Number(departmentId),
      reason,
      notes,
      taken_by: takenBy,
      date: when,
      items: [{ product_id: Number(productId), quantity: amount }],
    });
    if (!res || res.error) {
      setError(res?.error || "Could not save consumption.");
      return;
    }
    setNotes("");
    setQty("1");
    await qc.invalidateQueries({ queryKey: ["consumptions"] });
    await qc.invalidateQueries({ queryKey: ["products"] });
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
            Product
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-text"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
            >
              <option value="">Select</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.stock})</option>
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
              {["Cleaning", "Staff Consumption", "Office Use", "Production", "Damaged During Production", "Other"].map((r) => (
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
    </AppShell>
  );
}
