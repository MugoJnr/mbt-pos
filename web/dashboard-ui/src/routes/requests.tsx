import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui-kit";
import { GET } from "@/lib/api";

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
  ["refund", "Refund"],
  ["expense", "Expense"],
  ["price_override", "Price change"],
  ["credit", "Credit"],
  ["large_discount", "Large discount"],
] as const;

function RequestsCentrePage() {
  const navigate = useNavigate();
  const [queue, setQueue] = useState("all");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<CentreRow | null>(null);

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

  return (
    <AppShell title="Requests Centre">
      <PageHeader
        eyebrow="Overview"
        title="Requests Centre"
        description="Backdated sales, voids, refunds, expenses, price changes, credit, discounts, and stock requests. Debt is not a request — it is Debt Management. Opening a row does not create a sale, a void, or a stock change."
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
                className="block w-full px-3 py-3 text-left hover:bg-hover"
                onClick={() => setSelected(row)}
              >
                <div className="font-semibold">{row.reference}</div>
                <div className="text-sm text-text2">
                  {row.type_label} · {row.status_label} · {row.requester || "—"}
                </div>
                <div className="text-sm">
                  {row.submitted_at || "—"}
                  {row.business_date ? ` · business date ${row.business_date}` : ""}
                  {row.impact ? ` · ${row.impact}` : ""}
                </div>
                <div className="text-sm text-text2">{row.reason || "No reason"} · {row.next_action || ""}</div>
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
                <div className="text-base font-semibold">{selected.reference} · {selected.status_label}</div>
                <div>{selected.type_label} · {selected.requester || "—"}</div>
                <div>Submitted {selected.submitted_at || "—"}{selected.business_date ? ` · business date ${selected.business_date}` : ""}</div>
                <div>Next: {selected.next_action || "—"}</div>
                <div>Reason: {detail?.reason || detail?.current_reason || detail?.details || selected.reason || "—"}</div>
                {detail?.receipt ? (
                  <div>Receipt {detail.receipt.receipt_number} · {detail.receipt.status} · {detail.receipt.total}</div>
                ) : null}
                {(detail?.sales || []).map((sale: any, saleIndex: number) => (
                  <div key={saleIndex} className="rounded-lg border border-border p-3">
                    <div className="font-semibold">{sale.payment_method || "Cash"} · {sale.customer_name || "Walk-in"}</div>
                    {(sale.lines || []).map((line: any, lineIndex: number) => (
                      <div key={lineIndex}>
                        {line.product_name} · {line.quantity} × {line.unit_price}
                        {line.sku ? ` · ${line.sku}` : ""}
                      </div>
                    ))}
                  </div>
                ))}
                {(detail?.lines || []).map((line: any, lineIndex: number) => (
                  <div key={lineIndex}>{line.product_name} · {line.quantity} × {line.unit_price}</div>
                ))}
                {detail?.product_name ? (
                  <div>{detail.product_name}: stock {detail.current_stock} requested {detail.requested_qty}</div>
                ) : null}
                {detail?.review_note ? <div>Review note: {detail.review_note}</div> : null}
              </>
            )}
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
