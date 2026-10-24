import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Receipt } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Select, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES, todayISO } from "@/lib/format";

export const Route = createFileRoute("/receipts")({
  component: ReceiptsPage,
});

type ReceiptRow = {
  kind: string;
  id: number;
  reference: string;
  at?: string;
  user?: string;
  amount?: number | null;
  status?: string;
  display_status?: string;
  payment?: string;
  summary?: string;
};

const TYPES = [
  ["", "All types"],
  ["sale", "Sales"],
  ["consumption", "Internal consumption"],
  ["supplier", "Supplier deliveries"],
  ["debt_payment", "Debt repayments"],
  ["expense", "Expenses"],
  ["stock_adjustment", "Stock adjustments"],
  ["approval", "Approval requests"],
];

function ReceiptsPage() {
  const today = todayISO();
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<ReceiptRow | null>(null);
  const [restoreReason, setRestoreReason] = useState("");
  const [restoreMsg, setRestoreMsg] = useState("");
  const { user } = useAuth();
  const qc = useQueryClient();
  const limit = 25;

  const listQ = useQuery({
    queryKey: ["receipts", start, end, type, status, q, page],
    queryFn: () =>
      GET<{ receipts: ReceiptRow[]; total: number; error?: string }>("/receipts", {
        start,
        end,
        type,
        status,
        q,
        limit: String(limit),
        offset: String(page * limit),
      }),
  });

  const detailQ = useQuery({
    queryKey: ["receipt", open?.kind, open?.id],
    enabled: Boolean(open),
    queryFn: () => GET<any>(`/receipts/${open!.kind}/${open!.id}`),
  });

  const rows = listQ.data?.receipts || [];
  const total = Number(listQ.data?.total || 0);
  const pages = Math.max(1, Math.ceil(total / limit));
  const header = detailQ.data?.header || {};
  const lines = Array.isArray(detailQ.data?.lines) ? detailQ.data.lines : [];
  const history = Array.isArray(detailQ.data?.history) ? detailQ.data.history : [];
  const shownStatus = String(header.display_status || open?.display_status || header.status || (Number(header.voided || 0) === 1 ? "voided" : open?.status) || "");
  const canRestore = user?.role === "superadmin" && open && (
    (open.kind === "sale" && String(header.status || "").toLowerCase() === "voided")
    || (open.kind === "consumption" && Number(header.voided || 0) === 1)
  );
  const restoreM = useMutation({
    mutationFn: () => POST<any>(`/receipts/${open!.kind}/${open!.id}/restore`, { reason: restoreReason }),
    onSuccess: (data) => {
      if (!data || data.error || data.success === false) {
        setRestoreMsg(data?.error || "The receipt was not restored.");
        return;
      }
      setRestoreMsg(data.duplicate ? "This receipt is already active." : "Receipt restored.");
      setRestoreReason("");
      qc.invalidateQueries({ queryKey: ["receipts"] });
      qc.invalidateQueries({ queryKey: ["receipt", open?.kind, open?.id] });
    },
  });

  return (
    <AppShell title="All Receipts">
      <PageHeader
        eyebrow="Operations"
        title="All Receipts"
        icon={<Receipt className="h-4 w-4" />}
        description="Sales, consumption, deliveries, repayments, expenses, adjustments, and approval requests."
      />
      <Card className="mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
          <Input type="date" aria-label="From" value={start} onChange={(e) => { setPage(0); setStart(e.target.value); }} />
          <Input type="date" aria-label="To" value={end} onChange={(e) => { setPage(0); setEnd(e.target.value); }} />
          <Select aria-label="Type" value={type} onChange={(e) => { setPage(0); setType(e.target.value); }}>
            {TYPES.map(([value, label]) => (
              <option key={value || "all"} value={value}>{label}</option>
            ))}
          </Select>
          <Input aria-label="Status" placeholder="Status" value={status} onChange={(e) => { setPage(0); setStatus(e.target.value); }} />
          <Input aria-label="Search receipts" placeholder="Receipt, product, user" value={q} onChange={(e) => { setPage(0); setQ(e.target.value); }} />
        </div>
      </Card>
      <Card className="overflow-hidden">
        {listQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading receipts…</div>
        ) : listQ.isError || listQ.data?.error ? (
          <div className="py-12 text-center text-sm text-err">{listQ.data?.error || "Could not load receipts."}</div>
        ) : rows.length === 0 ? (
          <div className="py-12 text-center text-sm text-text2">No receipts in this filter.</div>
        ) : (
          <Table head={["When", "Type", "Reference", "User", "Amount", "Payment", "Status", ""]}>
            {rows.map((row) => (
              <tr key={`${row.kind}-${row.id}`}>
                <td className="px-4 py-2.5 text-text2">{String(row.at || "").replace("T", " ").slice(0, 19)}</td>
                <td className="px-4 py-2.5">{row.kind.replace(/_/g, " ")}</td>
                <td className="px-4 py-2.5 font-semibold text-text">{row.reference}</td>
                <td className="px-4 py-2.5">{row.user || "—"}</td>
                <td className="px-4 py-2.5 tabular-nums">{row.amount == null ? "—" : KES(row.amount)}</td>
                <td className="px-4 py-2.5">{row.payment || "—"}</td>
                <td className="px-4 py-2.5"><Badge tone={(row.display_status || row.status) === "voided" ? "err" : (row.display_status || row.status) === "pending" ? "warn" : "ok"}>{row.display_status || row.status}</Badge></td>
                <td className="px-4 py-2.5">
                  <Button size="sm" variant="ghost" onClick={() => setOpen(row)}>Open</Button>
                </td>
              </tr>
            ))}
          </Table>
        )}
        <div className="flex items-center justify-between px-4 py-3 text-xs text-text2">
          <span>{total} receipts</span>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</Button>
            <span className="self-center">Page {page + 1} / {pages}</span>
            <Button size="sm" variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      </Card>
      {open ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={() => setOpen(null)}>
          <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
            <Card className="max-h-[80vh] overflow-auto p-5">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-wide text-text2">{open.kind.replace(/_/g, " ")}</div>
                  <div className="text-lg font-extrabold text-text">{detailQ.data?.reference || open.reference}</div>
                </div>
                <Button variant="ghost" onClick={() => setOpen(null)}>Close</Button>
              </div>
              {detailQ.isLoading ? <div className="text-sm text-text2">Loading…</div> : null}
              {detailQ.data?.error ? <div className="text-sm text-err">{detailQ.data.error}</div> : null}
              <p className="mb-3 text-sm text-text2">{open.summary}</p>
              <div className="mb-3 grid grid-cols-2 gap-2 text-sm">
                <div>Status <span className="font-semibold text-text">{shownStatus || "—"}</span></div>
                <div>User <span className="font-semibold text-text">{header.cashier_name || header.username || header.created_by_name || open.user || "—"}</span></div>
                <div>Payment <span className="font-semibold text-text">{header.payment_method || open.payment || "—"}</span></div>
                <div>Total <span className="font-semibold text-text">{header.total == null && open.amount == null ? "—" : KES(header.total ?? open.amount)}</span></div>
              </div>
              {lines.length ? (
                <Table head={["Item", "Qty", "Price", "Total"]}>
                  {lines.map((line: any, index: number) => (
                    <tr key={index}>
                      <td className="px-4 py-2">{line.product_name || line.name || "—"}</td>
                      <td className="px-4 py-2 tabular-nums">{line.quantity}</td>
                      <td className="px-4 py-2 tabular-nums">{line.unit_price == null ? "—" : KES(line.unit_price)}</td>
                      <td className="px-4 py-2 tabular-nums">{line.total == null ? "—" : KES(line.total)}</td>
                    </tr>
                  ))}
                </Table>
              ) : null}
              {history.length ? (
                <div className="mt-3 space-y-1 text-sm">
                  <div className="font-semibold text-text">History</div>
                  {history.map((item: any, index: number) => (
                    <div key={index} className="text-text2">
                      {item.edit_type || item.action} · {item.edited_by_name || item.username || "—"} · {item.reason || item.details}
                    </div>
                  ))}
                </div>
              ) : null}
              {canRestore ? (
                <div className="mt-4 space-y-2">
                  <Input
                    aria-label="Reason for restoring this receipt"
                    placeholder="Reason for restoring this receipt"
                    value={restoreReason}
                    onChange={(e) => setRestoreReason(e.target.value)}
                  />
                  <Button
                    onClick={() => {
                      setRestoreMsg("");
                      if (!restoreReason.trim()) {
                        setRestoreMsg("Enter a reason for restoring this receipt.");
                        return;
                      }
                      restoreM.mutate();
                    }}
                    disabled={restoreM.isPending}
                  >
                    {restoreM.isPending ? "Restoring…" : "Un-void / Restore Receipt"}
                  </Button>
                </div>
              ) : null}
              {restoreMsg ? <div className="mt-3 text-sm text-text">{restoreMsg}</div> : null}
              {Array.isArray(detailQ.data?.approvals) && detailQ.data.approvals.length ? (
                <div className="mt-3 text-sm">
                  {detailQ.data.approvals.map((item: any) => (
                    <div key={item.id} className="text-text2">
                      Request {item.type} #{item.id} · {item.status} · {item.details || item.title}
                    </div>
                  ))}
                </div>
              ) : null}
            </Card>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
