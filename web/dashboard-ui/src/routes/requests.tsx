import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui-kit";
import { RequestReceiptDialog } from "@/components/request-receipt-dialog";
import { GET, POST, getUser } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/requests")({
  component: RequestsCentrePage,
});

type CentreRow = {
  source: string;
  source_id: number;
  reference: string;
  type: string;
  type_label: string;
  subject?: string;
  requester?: string;
  submitted_at?: string;
  business_date?: string;
  impact?: string;
  reason?: string;
  status: string;
  status_label: string;
  next_action?: string;
  requester_id?: number;
};

const QUEUES = [
  ["all", "All requests"],
  ["action", "Awaiting my action"],
  ["mine", "My requests"],
  ["pending", "Pending"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
  ["returned", "Returned for correction"],
] as const;

const TYPES = [
  ["", "All types"],
  ["backdated_sale", "Backdated sale"],
  ["void", "Sale void"],
  ["consumption_void", "Consumption void"],
  ["stock_adjustment", "Stock adjustment"],
  ["supplier_void", "Supplier delivery void"],
  ["supplier_backdate", "Supplier delivery backdate"],
  ["refund", "Refund"],
  ["expense", "Expense"],
  ["price_override", "Price change"],
  ["credit", "Credit"],
  ["large_discount", "Large discount"],
] as const;

function decisionCopy(row: CentreRow | null, detail: any) {
  const role = String(getUser()?.role || "").toLowerCase();
  const reviewer = ["manager", "admin", "superadmin"].includes(role);
  const status = String(detail?.status || row?.status || "").toLowerCase();
  const kind = String(detail?.type || row?.type || "");
  const source = String(row?.source || "");
  const awaiting = ["pending", "submitted", "escalated"].includes(status);
  const me = Number(getUser()?.id || 0);
  const own = me > 0 && Number(row?.requester_id || 0) === me;
  if (!row) {
    return { note: "Select a request. Approve and Reject are in this section.", approve: false, reject: false, back: false };
  }
  if (source === "backdate") {
    const open = reviewer && status === "submitted" && !own;
    return {
      approve: open, reject: open, back: open,
      note: own && status === "submitted"
        ? "You cannot approve your own backdated sale."
        : open
          ? "Approve posts this sale once. Reject does not."
          : `This request is ${status || "closed"}. The buttons stay visible.`,
    };
  }
  if (source === "delivery") {
    const open = ["admin", "superadmin"].includes(role) && awaiting && !own;
    const voiding = kind === "supplier_void";
    return {
      approve: open, reject: open, back: false,
      note: own && awaiting
        ? "You cannot approve your own supplier delivery request."
        : open && voiding && role !== "superadmin"
          ? "Approve asks for the Super-Admin PIN, then voids the delivery once."
          : open
            ? "Approve applies this supplier request once. Reject leaves the delivery unchanged."
            : "An admin uses Approve or Reject. A manager cannot change a supplier delivery.",
    };
  }
  if (source === "stock") {
    const open = role === "superadmin" && status === "pending";
    return {
      approve: open, reject: open, back: false,
      note: open ? "Only Super Admin can decide a stock adjustment." : "Only Super Admin can approve or reject a stock adjustment.",
    };
  }
  if (kind === "consumption_void") {
    const open = ["admin", "superadmin"].includes(role) && awaiting && !own;
    return {
      approve: open, reject: reviewer && awaiting && !own, back: false,
      note: own ? "You cannot approve your own consumption void." : open ? "Approve restores the stock once." : "An admin uses Approve or Reject.",
    };
  }
  if (kind === "void" || kind === "stock_adjust") {
    const open = (kind === "stock_adjust" ? role === "superadmin" : reviewer) && awaiting;
    return {
      approve: open, reject: open, back: false,
      note: open && role !== "superadmin"
        ? "Approve asks for the Super-Admin PIN, then runs once. Reject leaves the sale unchanged."
        : open
          ? "Approve runs once. Reject leaves the sale and stock unchanged."
          : reviewer
            ? `This request is ${status || "closed"}. The buttons stay visible.`
            : "A manager uses Approve or Reject. The sale stays completed until it is approved.",
    };
  }
  const open = reviewer && awaiting;
  return {
    approve: open, reject: open, back: false,
    note: open ? "Approve records the decision. It does not post a sale or change stock." : "A manager uses Approve or Reject.",
  };
}

function RequestsCentrePage() {
  const navigate = useNavigate();
  const [queue, setQueue] = useState("all");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<CentreRow | null>(null);
  const [openReceipt, setOpenReceipt] = useState(false);
  const [pin, setPin] = useState("");
  const [reason, setReason] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const role = String(getUser()?.role || "").toLowerCase();

  const listQ = useQuery({
    queryKey: ["requests-centre", queue, type, q],
    queryFn: () => GET<{ requests: CentreRow[]; counts?: Record<string, number>; error?: string }>(
      "/requests-centre",
      { queue, type, q },
    ),
  });
  const detailQ = useQuery({
    queryKey: ["requests-centre-item", selected?.source, selected?.source_id],
    queryFn: () => GET<any>(`/requests-centre/${selected!.source}/${selected!.source_id}`),
    enabled: Boolean(selected),
  });

  const rows = listQ.data?.requests || [];
  const counts = listQ.data?.counts || {};
  const detail = detailQ.data;
  const decision = decisionCopy(selected, detail);

  async function decide(action: "approve" | "reject" | "return") {
    if (!selected || busy) return;
    setDecisionError("");
    if (action !== "approve" && reason.trim().length < 3 && selected.source === "backdate") {
      setDecisionError("Enter a reason of at least 3 characters.");
      return;
    }
    const kind = String(detail?.type || selected.type || "");
    if (action === "approve" && role !== "superadmin" && (selected.source === "stock" || selected.source === "delivery" && kind === "supplier_void" || kind === "void" || kind === "stock_adjust") && !pin.trim()) {
      setDecisionError("Enter the Super-Admin PIN. Nothing changes until the server accepts it.");
      return;
    }
    setBusy(true);
    try {
      let result: { error?: string; success?: boolean } = {};
      if (selected.source === "backdate") {
        result = await POST(`/backdate-requests/${selected.source_id}/${action}`, action === "approve" ? {} : { reason });
      } else if (selected.source === "delivery") {
        result = await POST(`/supplier-delivery-requests/${selected.source_id}`, {
          decision: action === "approve" ? "approve" : "reject",
          note: reason,
          pin,
        });
      } else if (selected.source === "stock") {
        result = await POST(`/stock-adjustment-requests/${selected.source_id}/review`, {
          decision: action === "approve" ? "approved" : "rejected",
          pin,
          note: reason,
        });
      } else {
        result = await POST(`/approvals/${selected.source_id}/${action}`, action === "approve" ? { pin } : { note: reason });
      }
      if (!result || result.error || result.success === false) {
        setDecisionError(result?.error || "The request was not changed.");
        return;
      }
      setPin("");
      setReason("");
      await qc.invalidateQueries({ queryKey: ["requests-centre"] });
      await qc.invalidateQueries({ queryKey: ["requests-centre-item", selected.source, selected.source_id] });
    } finally {
      setBusy(false);
    }
  }

  const needsPin = role !== "superadmin" && (selected?.source === "stock" || selected?.type === "supplier_void" || selected?.type === "void" || selected?.type === "stock_adjust" || selected?.type === "stock_adjustment");
  const amountLabel = selected?.impact
    || (detail?.receipt?.total != null ? KES(Number(detail.receipt.total)) : "");
  const decisionBox = (
    <div className="rounded-xl border border-border bg-panel px-4 py-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-text2">Decision</div>
      <p className="mt-1 text-sm text-text2">{decision.note}</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason, if you reject or return" aria-label="Decision reason" />
        {needsPin ? (
          <Input type="password" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="Super-Admin PIN" aria-label="Super-Admin PIN" />
        ) : null}
      </div>
      {decisionError ? <p className="mt-2 text-sm text-err">{decisionError}</p> : null}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {decision.back ? (
          <Button variant="ghost" disabled={busy} onClick={() => decide("return")}>Return</Button>
        ) : null}
        <Button variant="secondary" disabled={!decision.reject || busy} onClick={() => decide("reject")}>Reject</Button>
        <Button variant="primary" disabled={!decision.approve || busy} onClick={() => decide("approve")}>Approve</Button>
      </div>
    </div>
  );

  return (
    <AppShell title="Requests Centre">
      <PageHeader
        eyebrow="Overview"
        title="Requests Centre"
        description="Backdated sales, sale voids, supplier delivery voids and backdates, refunds, expenses, price changes, credit, discounts, and stock requests. Debt is not a request — it is Debt Management. Opening a row does not create a sale, a void, or a stock change."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate({ to: "/backdating" })}>Backdating</Button>
            <Button variant="secondary" onClick={() => navigate({ to: "/void-requests" })}>Void Requests</Button>
            <Button variant="secondary" onClick={() => navigate({ to: "/approvals" })}>Approvals</Button>
            <Button variant="secondary" onClick={() => navigate({ to: "/debt" })}>Debt</Button>
            <Button onClick={() => navigate({ to: "/pos" })}>New Backdated Sale</Button>
          </div>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-4">
        <Card><div className="p-3 text-sm">All <span className="font-semibold">{counts.all ?? 0}</span></div></Card>
        <Card><div className="p-3 text-sm">Awaiting action <span className="font-semibold">{counts.action ?? 0}</span></div></Card>
        <Card><div className="p-3 text-sm">Pending <span className="font-semibold">{counts.pending ?? 0}</span></div></Card>
        <Card><div className="p-3 text-sm">Approved <span className="font-semibold">{counts.approved ?? 0}</span></div></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <Card>
          <div className="flex flex-wrap gap-2 border-b border-border p-3">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Reference, person, or reason" />
            <Select aria-label="Queue" value={queue} onChange={(e) => setQueue(e.target.value)}>
              {QUEUES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Select>
            <Select aria-label="Request type" value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
            </Select>
          </div>
          <div className="divide-y divide-border">
            {rows.map((row) => (
              <button
                key={`${row.source}-${row.source_id}`}
                type="button"
                className={`block w-full px-3 py-3 text-left hover:bg-hover ${selected?.source === row.source && selected?.source_id === row.source_id ? "bg-gold/10" : ""}`}
                onClick={() => { setSelected(row); setOpenReceipt(true); }}
              >
                <div className="font-semibold">{row.reference}</div>
                <div className="text-sm text-text2">
                  {row.type_label} · {row.status_label} · {row.requester || "—"}
                </div>
                <div className="text-sm">
                  {String(row.submitted_at || "—").replace("T", " ").slice(0, 19)}
                  {row.business_date ? ` · business date ${row.business_date}` : ""}
                  {row.impact ? ` · ${row.impact}` : ""}
                </div>
                <div className="text-xs font-semibold text-gold">View receipt</div>
              </button>
            ))}
            {!rows.length ? <div className="p-4 text-sm text-text2">No requests in this list.</div> : null}
          </div>
        </Card>
        <Card>
          <div className="space-y-2 p-4 text-sm">
            {!selected ? (
              <p className="text-text2">Select a request to read it. A past-day sale starts on Point of Sale. A void starts on Void Requests or a receipt. Refunds, expenses, price changes, credit, and discounts start on Approvals. Stock requests start on Inventory. Debt is Debt Management, not this list.</p>
            ) : detail?.error ? (
              <p>{detail.error}</p>
            ) : (
              <>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[11px] font-bold uppercase tracking-wide text-text2">{selected.type_label}</div>
                    <div className="mt-0.5 text-lg font-extrabold text-text">{selected.reference}</div>
                    <div className="text-sm text-text2">{selected.status_label} · {selected.requester || "—"}</div>
                  </div>
                  {amountLabel ? (
                    <div className="shrink-0 text-right">
                      <div className="text-[11px] font-bold uppercase tracking-wide text-text2">Amount</div>
                      <div className="text-xl font-extrabold tabular-nums text-gold">{amountLabel}</div>
                    </div>
                  ) : null}
                </div>
                <div className="text-sm text-text2">
                  {String(selected.submitted_at || "—").replace("T", " ").slice(0, 19)}
                  {selected.business_date ? ` · business date ${selected.business_date}` : ""}
                  {selected.next_action ? ` · ${selected.next_action}` : ""}
                </div>
                <div className="overflow-hidden rounded-lg border border-border">
                  <div className="grid grid-cols-[1fr_auto_auto] gap-3 border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
                    <span>Item</span><span className="text-right">Qty</span><span className="text-right">Amount</span>
                  </div>
                  {(detail?.lines || []).length === 0 && !(detail?.sales || []).length ? (
                    <div className="px-3 py-3 text-sm text-text2">No product lines on this request.</div>
                  ) : null}
                  {(detail?.lines || []).map((line: any, lineIndex: number) => (
                    <div key={lineIndex} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0">
                      <div className="font-medium text-text">{line.product_name || "Product"}</div>
                      <div className="text-right tabular-nums text-text2">{line.quantity}</div>
                      <div className="text-right font-semibold tabular-nums text-gold">{KES(Number(line.total ?? line.total_cost ?? line.unit_price ?? 0))}</div>
                    </div>
                  ))}
                  {(detail?.sales || []).map((sale: any, saleIndex: number) => (
                    (sale.lines || []).map((line: any, lineIndex: number) => (
                      <div key={`${saleIndex}-${lineIndex}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-border px-3 py-2 last:border-0">
                        <div className="font-medium text-text">{line.product_name || "Product"}</div>
                        <div className="text-right tabular-nums text-text2">{line.quantity}</div>
                        <div className="text-right font-semibold tabular-nums text-gold">{KES(Number(line.total ?? line.unit_price ?? 0))}</div>
                      </div>
                    ))
                  ))}
                </div>
                {amountLabel ? (
                  <div className="flex items-center justify-between rounded-lg border border-border bg-panel px-3 py-3">
                    <span className="text-sm text-text2">{detail?.kind === "consumption" ? "Stock cost" : "Receipt total"}</span>
                    <span className="text-lg font-extrabold tabular-nums text-gold">{amountLabel}</span>
                  </div>
                ) : null}
                <div className="text-sm">Reason <span className="font-semibold text-text">{detail?.reason || detail?.current_reason || detail?.details || selected.reason || "—"}</span></div>
                {detail?.product_name ? (
                  <div className="text-sm">{detail.product_name}: stock {detail.current_stock} requested {detail.requested_qty}</div>
                ) : null}
                {detail?.review_note ? <div className="text-sm">Review note: {detail.review_note}</div> : null}
                {decisionBox}
              </>
            )}
          </div>
        </Card>
      </div>
      {openReceipt && selected ? (
        <RequestReceiptDialog
          title={detail?.receipt?.receipt_number || selected.reference}
          status={detail?.receipt?.status || selected.status_label}
          reason={detail?.reason || detail?.current_reason || detail?.details || selected.reason}
          requester={selected.requester}
          submittedAt={selected.submitted_at}
          receipt={detail?.kind === "consumption" ? null : (detail?.receipt || (detail?.sales?.[0]?.id ? { id: detail.sales[0].id, receipt_number: detail.sales[0].receipt_number, total: detail.sales[0].total } : null))}
          consumption={detail?.kind === "consumption" ? detail?.consumption : null}
          lines={detail?.lines || detail?.sales?.[0]?.lines}
          note={detail?.error}
          onClose={() => setOpenReceipt(false)}
        >
          {decisionBox}
        </RequestReceiptDialog>
      ) : null}
    </AppShell>
  );
}
