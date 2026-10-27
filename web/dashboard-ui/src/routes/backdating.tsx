import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader } from "@/components/ui-kit";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/backdating")({
  component: BackdatingPage,
});

type Line = {
  product_id?: number;
  product_name?: string;
  quantity: number;
  unit_price: number;
  discount: number;
};
type Sale = {
  id?: number;
  payment_method: string;
  amount_paid: number;
  customer_id?: number | null;
  mpesa_ref?: string;
  notes?: string;
  lines: Line[];
  total?: number;
  posted_receipt?: string;
};
type RequestRow = {
  id: number;
  reference: string;
  cashier_name?: string;
  business_date: string;
  reason?: string;
  status: string;
  version: number;
  review_note?: string;
  submitted_at?: string;
  summary?: Record<string, number>;
  sales?: Sale[];
  warnings?: string[];
  events?: { action: string; actor_name?: string; note?: string; created_at?: string }[];
  error?: string;
};

const METHODS = ["Cash", "M-Pesa", "Bank Transfer", "Credit Sale", "Part Payment", "Mixed"];

function emptySale(): Sale {
  return { payment_method: "Cash", amount_paid: 0, lines: [{ quantity: 1, unit_price: 0, discount: 0 }] };
}

function BackdatingPage() {
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const canReview = role === "manager" || role === "admin" || role === "superadmin";
  const qc = useQueryClient();
  const [status, setStatus] = useState(canReview ? "submitted" : "");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [draftDate, setDraftDate] = useState("");
  const [draftReason, setDraftReason] = useState("");
  const [draftSales, setDraftSales] = useState<Sale[]>([emptySale()]);

  const listQ = useQuery({
    queryKey: ["backdate", status, query],
    queryFn: () => GET<{ requests: RequestRow[]; pending_count: number }>("/backdate-requests", {
      status,
      q: query,
    }),
  });
  const detailQ = useQuery({
    queryKey: ["backdate", selected],
    queryFn: () => GET<RequestRow>(`/backdate-requests/${selected}`),
    enabled: selected != null,
  });
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<{ id: number; name: string; price: number }[]>("/products"),
  });
  const customersQ = useQuery({
    queryKey: ["customers"],
    queryFn: () => GET<{ id: number; name: string }[]>("/customers"),
  });

  const rows = listQ.data?.requests || [];
  const detail = detailQ.data && !detailQ.data.error ? detailQ.data : null;
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const customers = Array.isArray(customersQ.data) ? customersQ.data : [];
  const pending = listQ.data?.pending_count || 0;
  const editable = !detail
    || detail.status === "draft"
    || detail.status === "returned"
    || (canReview && detail.status === "submitted");

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["backdate"] });
  };

  const run = useMutation({
    mutationFn: async (action: { path: string; body?: unknown; method?: "POST" | "PUT" }) => {
      const send = action.method === "PUT" ? PUT : POST;
      return send<RequestRow & { error?: string }>(action.path, action.body);
    },
    onSuccess: async (data) => {
      if (!data || data.error) {
        setMessage(data?.error || "The request was not saved.");
        return;
      }
      setMessage("");
      setSelected(data.id);
      await refresh();
    },
  });

  const payload = useMemo(() => ({
    business_date: draftDate,
    reason: draftReason,
    version: detail?.version,
    sales: draftSales,
  }), [draftDate, draftReason, draftSales, detail?.version]);

  async function loadDetail(row: RequestRow) {
    setSelected(row.id);
    const full = await GET<RequestRow>(`/backdate-requests/${row.id}`);
    if (!full || full.error) {
      setMessage(full?.error || "Could not open the request.");
      return;
    }
    setDraftDate(full.business_date || "");
    setDraftReason(full.reason || "");
    setDraftSales(full.sales?.length ? full.sales : [emptySale()]);
    setMessage("");
  }

  return (
    <AppShell>
      <PageHeader
        eyebrow="Sales"
        title="Backdating Requests"
        icon={<CalendarClock className="h-5 w-5" />}
        description={
          canReview
            ? `${pending} waiting for review. Approval is the only step that posts sales, stock, and debt.`
            : "Prepare sales for an earlier day. Nothing is posted until an administrator approves the request."
        }
        actions={<Button onClick={() => { setSelected(null); setDraftSales([emptySale()]); setDraftReason(""); }}>New request</Button>}
      />
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <div className="flex gap-2 p-3">
            <Input placeholder="Reference" value={query} onChange={(e) => setQuery(e.target.value)} />
            <select className="h-9 rounded-lg border border-border bg-card px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              <option value="draft">Draft</option>
              <option value="submitted">Pending</option>
              <option value="returned">Returned</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="withdrawn">Withdrawn</option>
            </select>
          </div>
          <div className="divide-y divide-border">
            {rows.map((row) => (
              <button key={row.id} className="block w-full px-3 py-3 text-left hover:bg-hover" onClick={() => loadDetail(row)}>
                <div className="font-semibold">{row.reference}</div>
                <div className="text-sm text-text2">{row.business_date} · {row.status} · {row.cashier_name}</div>
                <div className="text-sm">{row.summary?.total_sales ?? 0} · {row.summary?.sale_count ?? 0} sales</div>
              </button>
            ))}
            {!rows.length ? <div className="p-4 text-sm text-text2">No requests in this list.</div> : null}
          </div>
        </Card>
        <Card>
          <div className="space-y-3 p-4">
            {message ? <div className="rounded-lg bg-err/10 px-3 py-2 text-sm">{message}</div> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm">Business date
                <Input type="date" value={draftDate} disabled={!editable} onChange={(e) => setDraftDate(e.target.value)} />
              </label>
              <label className="text-sm">Status
                <Input value={detail?.status || "New draft"} disabled />
              </label>
            </div>
            <label className="block text-sm">Reason
              <textarea className="mt-1 min-h-20 w-full rounded-lg border border-border bg-card p-2" value={draftReason} disabled={!editable} onChange={(e) => setDraftReason(e.target.value)} />
            </label>
            {detail?.review_note ? <div className="text-sm">Administrator: {detail.review_note}</div> : null}
            {draftSales.map((sale, saleIndex) => (
              <div key={saleIndex} className="rounded-lg border border-border p-3">
                <div className="mb-2 font-semibold">Sale {saleIndex + 1}{sale.posted_receipt ? ` · ${sale.posted_receipt}` : ""}</div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <select className="h-9 rounded-lg border border-border bg-card px-2" disabled={!editable} value={sale.payment_method} onChange={(e) => updateSale(saleIndex, { payment_method: e.target.value })}>
                    {METHODS.map((method) => <option key={method}>{method}</option>)}
                  </select>
                  <Input type="number" disabled={!editable} value={sale.amount_paid} onChange={(e) => updateSale(saleIndex, { amount_paid: Number(e.target.value) })} placeholder="Amount received" />
                  <select className="h-9 rounded-lg border border-border bg-card px-2" disabled={!editable} value={sale.customer_id || ""} onChange={(e) => updateSale(saleIndex, { customer_id: e.target.value ? Number(e.target.value) : null })}>
                    <option value="">No customer</option>
                    {customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}
                  </select>
                  <Input disabled={!editable} value={sale.mpesa_ref || ""} placeholder="M-Pesa reference, if any" onChange={(e) => updateSale(saleIndex, { mpesa_ref: e.target.value })} />
                  <Input disabled={!editable} value={sale.notes || ""} placeholder="Note" onChange={(e) => updateSale(saleIndex, { notes: e.target.value })} />
                </div>
                {sale.lines.map((line, lineIndex) => (
                  <div key={lineIndex} className="mt-2 grid gap-2 sm:grid-cols-4">
                    <select className="h-9 rounded-lg border border-border bg-card px-2" disabled={!editable} value={line.product_id || ""} onChange={(e) => {
                      const product = products.find((item) => item.id === Number(e.target.value));
                      updateLine(saleIndex, lineIndex, {
                        product_id: product?.id,
                        product_name: product?.name,
                        unit_price: line.unit_price || product?.price || 0,
                      });
                    }}>
                      <option value="">Product</option>
                      {products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
                    </select>
                    <Input type="number" disabled={!editable} value={line.quantity} onChange={(e) => updateLine(saleIndex, lineIndex, { quantity: Number(e.target.value) })} />
                    <Input type="number" disabled={!editable} value={line.unit_price} onChange={(e) => updateLine(saleIndex, lineIndex, { unit_price: Number(e.target.value) })} />
                    <Input type="number" disabled={!editable} value={line.discount} onChange={(e) => updateLine(saleIndex, lineIndex, { discount: Number(e.target.value) })} />
                  </div>
                ))}
                {editable ? (
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" onClick={() => updateSale(saleIndex, { lines: [...sale.lines, { quantity: 1, unit_price: 0, discount: 0 }] })}>Add product</Button>
                    <Button size="sm" variant="ghost" onClick={() => setDraftSales(draftSales.filter((_, index) => index !== saleIndex))}>Remove sale</Button>
                  </div>
                ) : null}
              </div>
            ))}
            {editable ? <Button variant="secondary" onClick={() => setDraftSales([...draftSales, emptySale()])}>Add sale</Button> : null}
            {detail?.summary ? (
              <div className="grid gap-2 text-sm sm:grid-cols-3">
                <div>Total {detail.summary.total_sales}</div>
                <div>Cash {detail.summary.cash_sales}</div>
                <div>M-Pesa {detail.summary.mpesa_sales}</div>
                <div>Bank {detail.summary.bank_sales}</div>
                <div>Credit {detail.summary.credit_sales}</div>
                <div>Debt created {detail.summary.outstanding_debt}</div>
              </div>
            ) : null}
            {(detail?.warnings || []).map((warning) => <div key={warning} className="text-sm text-err">{warning}</div>)}
            <div className="flex flex-wrap gap-2">
              {editable ? <Button onClick={() => save(false)} disabled={run.isPending}>Save draft</Button> : null}
              {editable && detail ? <Button variant="primary" onClick={() => save(true)} disabled={run.isPending}>Submit</Button> : null}
              {detail && ["draft", "submitted", "returned"].includes(detail.status) && !canReview ? (
                <Button variant="danger" onClick={() => act("withdraw")}>Withdraw</Button>
              ) : null}
              {canReview && detail?.status === "submitted" ? (
                <>
                  <Button variant="success" onClick={() => act("approve")}>Approve and post</Button>
                  <Button onClick={() => act("return")}>Return for correction</Button>
                  <Button variant="danger" onClick={() => act("reject")}>Reject</Button>
                </>
              ) : null}
            </div>
            {(detail?.events || []).map((event, index) => (
              <div key={index} className="text-xs text-text2">{event.created_at} · {event.actor_name} · {event.action} {event.note}</div>
            ))}
          </div>
        </Card>
      </div>
    </AppShell>
  );

  function updateSale(index: number, patch: Partial<Sale>) {
    setDraftSales(draftSales.map((sale, saleIndex) => saleIndex === index ? { ...sale, ...patch } : sale));
  }
  function updateLine(saleIndex: number, lineIndex: number, patch: Partial<Line>) {
    setDraftSales(draftSales.map((sale, index) => {
      if (index !== saleIndex) return sale;
      return { ...sale, lines: sale.lines.map((line, current) => current === lineIndex ? { ...line, ...patch } : line) };
    }));
  }
  async function save(submit: boolean) {
    const body = payload;
    let current = detail;
    if (!current) {
      const created = await POST<RequestRow & { error?: string }>("/backdate-requests", body);
      if (!created || created.error) {
        setMessage(created?.error || "The request was not saved.");
        return;
      }
      current = created;
    } else {
      const updated = await PUT<RequestRow & { error?: string }>(`/backdate-requests/${current.id}`, body);
      if (!updated || updated.error) {
        setMessage(updated?.error || "The request was not saved.");
        return;
      }
      current = updated;
    }
    if (submit) {
      const submitted = await POST<RequestRow & { error?: string }>(
        `/backdate-requests/${current.id}/submit`,
        { version: current.version },
      );
      if (!submitted || submitted.error) {
        setMessage(submitted?.error || "The request was not submitted.");
        setSelected(current.id);
        await refresh();
        return;
      }
      current = submitted;
    }
    setMessage("");
    setSelected(current.id);
    await refresh();
  }
  function act(action: "approve" | "return" | "reject" | "withdraw") {
    if (!detail) return;
    const needsNote = action !== "approve";
    const note = needsNote ? window.prompt(action === "withdraw" ? "Why are you withdrawing this request?" : "Enter the reason") : "";
    if (needsNote && !note) return;
    const confirmed = action !== "approve" || window.confirm(
      `Post ${detail.summary?.sale_count || 0} sales totalling ${detail.summary?.total_sales || 0}? This cannot be edited afterwards.`,
    );
    if (!confirmed) return;
    run.mutate({
      path: `/backdate-requests/${detail.id}/${action}`,
      body: { version: detail.version, reason: note || "", note: note || "" },
    });
  }
}
