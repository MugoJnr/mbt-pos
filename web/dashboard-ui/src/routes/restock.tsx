import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { ListChecks } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader } from "@/components/ui-kit";
import { DEL, GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/restock")({
  component: RestockPage,
});

type RestockLine = {
  id: number;
  line_id?: number;
  product_id?: number;
  product_name?: string;
  sku?: string;
  quantity?: number;
  quantity_text?: string;
  unit?: string;
  notes?: string;
  purchased_qty?: number;
  unavailable_qty?: number;
  outstanding_qty?: number;
  received_qty?: number;
  rejected_qty?: number;
  purchased_not_received?: number;
  purchase_notes?: string;
  unit_price?: number;
};

type RestockRequest = {
  id: number;
  reference: string;
  name: string;
  description?: string;
  status: string;
  status_label: string;
  priority: string;
  created_name?: string;
  created_at?: string;
  updated_at?: string;
  buyer_name?: string;
  buyer_user_id?: number;
  external_buyer?: string;
  desired_date?: string;
  instructions?: string;
  version: number;
  product_count?: number;
  lines?: RestockLine[];
  snapshot?: { revision_no: number; submitted_name?: string; lines: RestockLine[] } | null;
  history?: { kind: string; detail?: string; username?: string; created_at?: string; before_value?: string; after_value?: string }[];
  error?: string;
  conflict?: boolean;
};

type ProductHit = { id: number; name: string; sku?: string; unit?: string; stock?: number };
type Suggestion = { product_id: number; product_name: string; unit?: string; stock?: number; suggested_qty?: number; out_of_stock?: boolean };

function allows(user: { effective_permissions?: unknown; role?: string } | null, action: string) {
  const list = Array.isArray(user?.effective_permissions) ? user.effective_permissions.map(String) : null;
  if (list) return list.includes(action);
  const role = String(user?.role || "");
  if (action === "restock.view") return ["viewer", "manager", "admin", "superadmin"].includes(role);
  return ["manager", "admin", "superadmin"].includes(role);
}

function RestockPage() {
  const { user } = useAuth();
  const canCreate = allows(user, "restock.create") || allows(user, "restock.manage");
  const canManage = allows(user, "restock.manage");
  const canPurchase = allows(user, "restock.purchase");
  const canReceive = canManage && allows(user, "inventory.receive");
  const canCost = allows(user, "inventory.view_cost");
  const [rows, setRows] = useState<RestockRequest[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [creator, setCreator] = useState("");
  const [buyerFilter, setBuyerFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [current, setCurrent] = useState<RestockRequest | null>(null);
  const [saveState, setSaveState] = useState("Saved");
  const [productQuery, setProductQuery] = useState("");
  const [products, setProducts] = useState<ProductHit[]>([]);
  const [quantity, setQuantity] = useState("1");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [buyers, setBuyers] = useState<{ id: number; name: string }[]>([]);
  const [buyerId, setBuyerId] = useState("");
  const [externalBuyer, setExternalBuyer] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [suppliers, setSuppliers] = useState<{ id: number; name: string }[]>([]);

  async function loadList() {
    const data = await GET<{ requests?: RestockRequest[]; error?: string }>("/restock-requests", {
      q: query,
      status,
      archived: status === "archived" ? "1" : "",
      creator,
      buyer: buyerFilter,
      date_from: dateFrom,
      date_to: dateTo,
    });
    if (data?.error) {
      toast.error(data.error);
      return;
    }
    setRows(data?.requests || []);
  }

  async function openRequest(id: number) {
    const data = await GET<{ request?: RestockRequest; error?: string }>(`/restock-requests/${id}`);
    if (data?.error || !data?.request) {
      toast.error(data?.error || "That list could not be opened.");
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    setBuyerId(String(data.request.buyer_user_id || ""));
    setExternalBuyer(data.request.external_buyer || "");
  }

  useEffect(() => { loadList(); }, [query, status, creator, buyerFilter, dateFrom, dateTo]);
  useEffect(() => {
    GET<{ suggestions?: Suggestion[] }>("/restock-requests/suggestions").then((data) => setSuggestions(data?.suggestions || []));
    if (canManage) {
      GET<{ buyers?: { id: number; name: string }[] }>("/restock-requests/buyers").then((data) => setBuyers(data?.buyers || []));
      GET<Array<{ id: number; name: string }> | { suppliers?: { id: number; name: string }[]; error?: string }>("/suppliers").then((data) => {
        const rows = Array.isArray(data) ? data : data?.suppliers || [];
        setSuppliers(rows);
      });
    }
  }, [canManage]);

  useEffect(() => {
    const handle = window.setTimeout(async () => {
      const data = await GET<{ products?: ProductHit[] }>("/restock-requests/products", { q: productQuery });
      setProducts(data?.products || []);
    }, 250);
    return () => window.clearTimeout(handle);
  }, [productQuery]);

  const summary = useMemo(() => {
    const lines = current?.lines || [];
    const units = new Set(lines.map((line) => line.unit || ""));
    return { count: lines.length, mixed: units.size > 1 };
  }, [current]);

  async function createList() {
    const name = window.prompt("List name", "General Shop Restock");
    if (!name) return;
    setSaveState("Saving...");
    const data = await POST<{ request?: RestockRequest; error?: string }>("/restock-requests", { name, priority: "normal" });
    if (data?.error || !data?.request) {
      setSaveState("Not saved");
      toast.error(data?.error || "The list was not saved.");
      return;
    }
    setSaveState("Saved");
    setCurrent(data.request);
    loadList();
  }

  async function saveHeader(patch: Record<string, unknown>) {
    if (!current) return;
    setSaveState("Saving...");
    const data = await PUT<{ request?: RestockRequest; error?: string; conflict?: boolean }>(`/restock-requests/${current.id}`, {
      version: current.version, ...patch,
    });
    if (data?.conflict) {
      setSaveState("Not saved");
      toast.error(data.error || "Someone else saved this list.");
      openRequest(current.id);
      return;
    }
    if (data?.error || !data?.request) {
      setSaveState("Not saved");
      toast.error(data?.error || "The list was not saved.");
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    loadList();
  }

  async function addProduct(productId: number, qty = quantity, merge = false) {
    if (!current) {
      toast.error("Create or open a list first.");
      return;
    }
    const data = await POST<{ request?: RestockRequest; error?: string; status?: number; existing_line_id?: number }>(
      `/restock-requests/${current.id}/lines`,
      { version: current.version, product_id: productId, quantity: qty, merge },
    );
    if (data?.existing_line_id && !merge) {
      if (window.confirm("That product is already on this list. Add to its quantity?")) {
        await addProduct(productId, qty, true);
      }
      return;
    }
    if (data?.error || !data?.request) {
      toast.error(data?.error || "The product was not added.");
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    loadList();
  }

  async function act(path: string, body?: unknown) {
    if (!current) return;
    const data = await POST<{ request?: RestockRequest; error?: string; html?: string }>(`/restock-requests/${current.id}/${path}`, {
      version: current.version, ...(body as object || {}),
    });
    if (data?.html) {
      const page = window.open("", "_blank");
      if (page) {
        page.document.write(data.html);
        page.document.close();
      }
      return;
    }
    if (data?.error || !data?.request) {
      toast.error(data?.error || "That action was not saved.");
      if (current) openRequest(current.id);
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    loadList();
  }

  async function printReceipt(paper: string) {
    if (!current) return;
    const preview = await GET<{ text?: string; error?: string }>(`/restock-requests/${current.id}/document`, { format: "thermal", paper });
    if (preview?.error || !preview?.text) {
      toast.error(preview?.error || "The request could not be prepared for the receipt printer.");
      return;
    }
    const sent = await POST<{ message?: string; error?: string; printed?: boolean }>("/print/direct", {
      kind: "restock", id: current.id, reprint: true,
    });
    const page = window.open("", "_blank");
    if (page) {
      page.document.write(`<pre style="font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;max-width:${paper === "58" ? "58mm" : "80mm"}">${preview.text.replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch] || ch))}</pre>`);
      page.document.close();
    }
    toast.message(sent?.message || (sent?.printed ? "Sent to the receipt printer." : "No receipt printer is connected. The request is shown on screen and can be saved as a PDF."));
  }

  async function savePdf() {
    if (!current) return;
    const token = localStorage.getItem("mbt_token") || "";
    const response = await fetch(`/api/restock-requests/${current.id}/document?format=a4`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      toast.error("The PDF was not saved. The request itself is unchanged.");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${current.reference || "restock"}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function changeQty(lineId: number, quantity: string) {
    if (!current) return;
    const data = await PUT<{ request?: RestockRequest; error?: string }>(
      `/restock-requests/${current.id}/lines/${lineId}`,
      { version: current.version, quantity },
    );
    if (data?.error || !data?.request) {
      toast.error(data?.error || "The quantity was not saved.");
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    loadList();
  }

  async function removeLine(lineId: number) {
    if (!current) return;
    const data = await DEL<{ request?: RestockRequest; error?: string }>(
      `/restock-requests/${current.id}/lines/${lineId}?version=${current.version}`,
    );
    if (data?.error || !data?.request) {
      toast.error(data?.error || "The product was not removed.");
      return;
    }
    setCurrent(data.request);
    setSaveState("Saved");
    loadList();
  }

  return (
    <AppShell title="Restocking Requests">
      <PageHeader
        eyebrow="Inventory"
        title="Restocking Requests"
        icon={<ListChecks className="h-4 w-4" />}
        description="Create and manage lists of products the shop needs to purchase. A list does not change stock. This shop's till and this dashboard read the same saved lists."
        actions={null}
      />
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card className="p-3 space-y-3">
          {canCreate ? <Button variant="primary" className="w-full" onClick={createList}>New Restock List</Button> : null}
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or reference" />
          <select className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Active lists</option>
            {["draft", "ready", "assigned", "partial_purchased", "purchased", "partial_received", "received", "cancelled", "archived"].map((item) => (
              <option key={item} value={item}>{item.split("_").join(" ")}</option>
            ))}
          </select>
          {canManage ? (
            <>
              <select className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm" value={creator} onChange={(event) => setCreator(event.target.value)}>
                <option value="">Any creator</option>
                {buyers.map((person) => <option key={`c-${person.id}`} value={person.id}>{person.name}</option>)}
              </select>
              <select className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm" value={buyerFilter} onChange={(event) => setBuyerFilter(event.target.value)}>
                <option value="">Any buyer</option>
                {buyers.map((person) => <option key={`b-${person.id}`} value={person.id}>{person.name}</option>)}
              </select>
            </>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-label="From date" />
            <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-label="To date" />
          </div>
          <div className="space-y-2">
            {rows.length === 0 ? <p className="text-sm text-text2">No restock lists yet.</p> : null}
            {rows.map((row) => (
              <button key={row.id} className="w-full rounded-lg border border-border px-3 py-2 text-left hover:bg-hover" onClick={() => openRequest(row.id)}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-text">{row.name}</span>
                  <Badge tone={row.status === "draft" ? "muted" : row.status.includes("received") ? "ok" : "gold"}>{row.status_label}</Badge>
                </div>
                <p className="text-xs text-text2">{row.reference} · {row.product_count || 0} {row.product_count === 1 ? "product" : "products"} · {row.created_name || "Staff"}</p>
              </button>
            ))}
          </div>
        </Card>
        <div className="space-y-4">
          {!current ? <Card className="p-6 text-text2">Open a list or create a new one. Lists stay saved when you close the till.</Card> : (
            <Card className="p-4 space-y-4">
              <div>
                <p className="text-xs text-text2">{current.reference}</p>
                <input
                  className="w-full bg-transparent text-xl font-semibold text-text outline-none"
                  value={current.name}
                  disabled={current.status !== "draft" || !canCreate}
                  onChange={(event) => setCurrent({ ...current, name: event.target.value })}
                  onBlur={() => saveHeader({ name: current.name })}
                />
                <p className="text-sm text-text2">{saveState} · {current.status_label} · {current.created_name}</p>
              </div>
              <textarea
                rows={2}
                className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm"
                placeholder="Instructions for the buyer"
                value={current.instructions || ""}
                disabled={current.status !== "draft" || !canCreate}
                onChange={(event) => setCurrent({ ...current, instructions: event.target.value })}
                onBlur={() => saveHeader({ instructions: current.instructions || "" })}
              />
              <div className="space-y-2">
                {canManage || canCreate || current.status === "draft" ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-text2">List</span>
                    {canManage && current.status === "draft" ? <Button onClick={() => act("submit")}>Mark Ready</Button> : null}
                    {canManage && (current.status === "ready" || current.status === "assigned") ? <Button variant="secondary" onClick={() => act("return-to-draft")}>Return to draft</Button> : null}
                    {canCreate ? <Button variant="ghost" onClick={() => act("duplicate")}>Duplicate</Button> : null}
                    {canManage || current.status === "draft" ? <Button variant="ghost" onClick={() => act("archive")}>Archive</Button> : null}
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-text2">Output</span>
                  <Button variant="secondary" onClick={() => printReceipt("58")}>Print 58 mm</Button>
                  <Button variant="secondary" onClick={() => printReceipt("80")}>Print 80 mm</Button>
                  <Button variant="ghost" onClick={() => savePdf()}>Save as PDF</Button>
                </div>
              </div>
              <p className="text-sm text-text2">{summary.count} products{summary.mixed ? ". Quantities use different units, so there is no single total." : "."}</p>
              {current.status === "draft" && canCreate ? (
                <div className="grid gap-2 sm:grid-cols-[1fr_120px_auto]">
                  <Input value={productQuery} onChange={(event) => setProductQuery(event.target.value)} placeholder="Search product, SKU, or barcode" />
                  <Input value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="Qty" />
                  <Button onClick={() => products[0] && addProduct(products[0].id)}>Add</Button>
                </div>
              ) : null}
              {current.status === "draft" && products.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {products.slice(0, 8).map((product) => (
                    <button key={product.id} className="rounded-md border border-border px-2 py-1 text-sm" onClick={() => addProduct(product.id)}>
                      {product.name} · {product.unit || "unit"}
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="min-h-[240px]">
                <table className="w-full table-fixed text-sm">
                  <thead>
                    <tr className="text-left text-text2">
                      <th className="w-[28%] py-2 pr-2">Product</th>
                      <th className="w-[12%]">Requested</th>
                      <th className="w-[10%]">Purchased</th>
                      <th className="w-[12%]">Outstanding</th>
                      <th className="w-[14%]">Received</th>
                      <th className="w-[10%]">Rejected</th>
                      <th className="w-[14%]">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(current.lines || []).length === 0 ? (
                      <tr>
                        <td colSpan={7} className="py-16 text-center text-text2">No products have been added yet.</td>
                      </tr>
                    ) : null}
                    {(current.lines || []).map((line) => (
                      <tr key={line.id} className="border-t border-border">
                        <td className="py-2 pr-2">{line.product_name}<div className="text-xs text-text2">{line.sku}</div></td>
                        <td>
                          {current.status === "draft" && canCreate ? (
                            <Input className="h-8 w-full max-w-[6.5rem]" defaultValue={String(line.quantity_text || line.quantity || "")} onBlur={(event) => changeQty(line.line_id || line.id, event.target.value)} />
                          ) : (
                            <>{line.quantity_text} {line.unit}</>
                          )}
                        </td>
                        <td>{line.purchased_qty || 0}</td>
                        <td>{line.outstanding_qty || 0}</td>
                        <td>{line.received_qty || 0}{line.purchased_not_received ? ` · ${line.purchased_not_received} bought, not here` : ""}</td>
                        <td>{line.rejected_qty || 0}</td>
                        <td>
                          {line.notes || line.purchase_notes || ""}
                          {current.status === "draft" && canCreate ? (
                            <button type="button" className="ml-2 text-xs underline" onClick={() => removeLine(line.line_id || line.id)}>Remove</button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {canManage && current.status !== "draft" && current.status !== "cancelled" && current.status !== "archived" ? (
                <div className="flex flex-wrap gap-2">
                  <select className="rounded-md border border-border bg-card px-2 py-2 text-sm" value={buyerId} onChange={(event) => setBuyerId(event.target.value)}>
                    <option value="">Staff buyer</option>
                    {buyers.map((buyer) => <option key={buyer.id} value={buyer.id}>{buyer.name}</option>)}
                  </select>
                  <Input value={externalBuyer} onChange={(event) => setExternalBuyer(event.target.value)} placeholder="External buyer name" />
                  <Button variant="secondary" onClick={() => act("assign", { buyer_user_id: buyerId || null, external_buyer: externalBuyer })}>Assign</Button>
                </div>
              ) : null}
              {canPurchase && current.snapshot ? (
                <PurchaseBox current={current} canCost={canCost} onSave={(lines) => act("purchase", { lines })} />
              ) : null}
              {canReceive && current.status !== "draft" ? (
                <ReceiveBox
                  lines={current.lines || []}
                  suppliers={suppliers}
                  supplierId={supplierId}
                  setSupplierId={setSupplierId}
                  onReceive={(lineId, qty, rejected) => act("receive", { line_id: lineId, quantity: qty, qty_rejected: rejected, supplier_id: supplierId, client_token: `restock-${current.id}-${lineId}-${Date.now()}` })}
                />
              ) : null}
              <div>
                <p className="text-sm font-semibold">History</p>
                {(current.history || []).slice(-8).map((event, index) => (
                  <p key={`${event.kind}-${index}`} className="text-xs text-text2">{event.created_at} · {event.username} · {event.kind} {event.detail || event.after_value || ""}</p>
                ))}
              </div>
            </Card>
          )}
          {suggestions.length > 0 && current?.status === "draft" && canCreate ? (
            <Card className="p-4">
              <p className="font-semibold">Low and out of stock</p>
              <p className="text-sm text-text2 mb-2">Suggested from the reorder level. Nothing is ordered until you add it.</p>
              <div className="flex flex-wrap gap-2">
                {suggestions.slice(0, 12).map((item) => (
                  <button key={item.product_id} className="rounded-md border border-border px-2 py-1 text-sm" onClick={() => addProduct(item.product_id, String(item.suggested_qty || 1))}>
                    {item.product_name} · suggest {item.suggested_qty} {item.unit}
                  </button>
                ))}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}

function PurchaseBox({ current, canCost, onSave }: { current: RestockRequest; canCost: boolean; onSave: (lines: object[]) => void }) {
  const [qty, setQty] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Record<number, string>>({});
  return (
    <div className="space-y-2">
      <p className="font-semibold">What was purchased</p>
      <p className="text-sm text-text2">This records the buyer's result. It does not receive the goods or change stock.</p>
      {(current.lines || []).map((line) => (
        <div key={line.id} className="grid gap-2 sm:grid-cols-[1fr_120px_1fr]">
          <span className="text-sm">{line.product_name}</span>
          <Input value={qty[line.id] ?? String(line.purchased_qty || 0)} onChange={(event) => setQty({ ...qty, [line.id]: event.target.value })} />
          <Input value={notes[line.id] ?? (line.purchase_notes || "")} placeholder="Buyer note" onChange={(event) => setNotes({ ...notes, [line.id]: event.target.value })} />
          {canCost ? null : null}
        </div>
      ))}
      <Button variant="secondary" onClick={() => onSave((current.lines || []).map((line) => ({
        id: line.id,
        purchased_qty: qty[line.id] ?? line.purchased_qty ?? 0,
        notes: notes[line.id] ?? line.purchase_notes ?? "",
      })))}>Save purchase progress</Button>
    </div>
  );
}

function ReceiveBox({ lines, suppliers, supplierId, setSupplierId, onReceive }: {
  lines: RestockLine[];
  suppliers: { id: number; name: string }[];
  supplierId: string;
  setSupplierId: (value: string) => void;
  onReceive: (lineId: number, quantity: string, rejected: string) => void;
}) {
  const [lineId, setLineId] = useState(String(lines[0]?.line_id || ""));
  const [qty, setQty] = useState("1");
  const [rejected, setRejected] = useState("0");
  return (
    <div className="space-y-2">
      <p className="font-semibold">Goods arrived</p>
      <p className="text-sm text-text2">Accepted quantity goes through the normal supplier delivery. Rejected or damaged quantity is not added to stock.</p>
      <div className="grid gap-2 sm:grid-cols-5">
        <select className="rounded-md border border-border bg-card px-2 py-2 text-sm" value={supplierId} onChange={(event) => setSupplierId(event.target.value)}>
          <option value="">Supplier</option>
          {suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
        </select>
        <select className="rounded-md border border-border bg-card px-2 py-2 text-sm" value={lineId} onChange={(event) => setLineId(event.target.value)}>
          {lines.map((line) => <option key={line.line_id || line.id} value={line.line_id || line.id}>{line.product_name}</option>)}
        </select>
        <Input aria-label="Accepted quantity" value={qty} onChange={(event) => setQty(event.target.value)} placeholder="Accepted" />
        <Input aria-label="Rejected quantity" value={rejected} onChange={(event) => setRejected(event.target.value)} placeholder="Rejected" />
        <Button onClick={() => onReceive(Number(lineId), qty, rejected)}>Receive goods</Button>
      </div>
    </div>
  );
}
