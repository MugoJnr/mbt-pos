import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Select } from "@/components/ui-kit";
import { RequestReceiptDialog } from "@/components/request-receipt-dialog";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/void-requests")({
  component: VoidRequestsPage,
});

type VoidRequest = {
  id: number;
  receipt_number?: string;
  sale_id?: number;
  requested_by?: string;
  created_at?: string;
  updated_at?: string;
  amount?: number;
  status?: string;
  original_reason?: string;
  current_reason?: string;
  reviewed_by?: string;
  review_note?: string;
  history?: { at?: string; action?: string; by?: string; reason?: string; note?: string }[];
  receipt?: { id?: number; receipt_number?: string; status?: string; total?: number; cashier_name?: string; payment_method?: string; amount_paid?: number; customer_name?: string; sale_date?: string; created_at?: string } | null;
  receipt_note?: string;
  lines?: { product_name?: string; quantity?: number; unit_price?: number; total?: number }[];
  error?: string;
};

function VoidRequestsPage() {
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const sessionSuper = role === "superadmin";
  const canReview = ["manager", "admin", "superadmin"].includes(role);
  const qc = useQueryClient();
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [pin, setPin] = useState("");
  const [msg, setMsg] = useState("");
  const limit = 25;

  const listQ = useQuery({
    queryKey: ["void-requests", status, q, page],
    queryFn: () =>
      GET<{ requests: VoidRequest[]; total: number; error?: string }>("/void-requests", {
        status,
        q,
        limit: String(limit),
        offset: String(page * limit),
      }),
  });
  const detailQ = useQuery({
    queryKey: ["void-request", openId],
    enabled: openId != null,
    queryFn: () => GET<VoidRequest>(`/void-requests/${openId}`),
  });

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["void-requests"] });
    await qc.invalidateQueries({ queryKey: ["void-request", openId] });
  };
  const correctM = useMutation({
    mutationFn: () => PUT<any>(`/void-requests/${openId}`, { reason: draft }),
    onSuccess: async (data) => {
      setMsg(data?.error || "Reason saved. The original request is still shown.");
      if (!data?.error) await refresh();
    },
  });
  const resubmitM = useMutation({
    mutationFn: () => POST<any>(`/void-requests/${openId}/resubmit`, {}),
    onSuccess: async (data) => {
      setMsg(data?.error || "Sent back for review.");
      if (!data?.error) await refresh();
    },
  });
  const returnM = useMutation({
    mutationFn: () => POST<any>(`/void-requests/${openId}/return`, { note }),
    onSuccess: async (data) => {
      setMsg(data?.error || "Returned for correction.");
      if (!data?.error) await refresh();
    },
  });
  const decideM = useMutation({
    mutationFn: (action: "approve" | "reject") => {
      if (action === "approve" && !sessionSuper && !pin.trim()) {
        return Promise.resolve({
          error: "Enter the Super-Admin PIN. The receipt stays completed until the server accepts it.",
        });
      }
      return POST<any>(
        `/approvals/${openId}/${action}`,
        action === "approve" ? { pin, note } : { note },
      );
    },
    onSuccess: async (data) => {
      setMsg(data?.error || data?.message || "Review saved.");
      if (!data?.error) await refresh();
    },
  });

  const rows = listQ.data?.requests || [];
  const total = Number(listQ.data?.total || 0);
  const pages = Math.max(1, Math.ceil(total / limit));
  const event = detailQ.data;
  const opened = rows.find((row) => row.id === openId);
  const locked = ["approved", "rejected", "cancelled", "expired"].includes(String(event?.status || ""));
  const tone = (value?: string) =>
    value === "approved" ? "ok" : value === "rejected" || value === "cancelled" ? "err" : value === "returned" ? "warn" : "muted";

  return (
    <AppShell title="Void Requests">
      <PageHeader
        eyebrow="Overview"
        title="Void Requests"
        icon={<Ban className="h-4 w-4" />}
        description="A request asks for a void. The receipt stays completed until the request is approved. A signed-in Super Admin can void a receipt directly from the receipt instead."
      />
      <Card className="mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Input aria-label="Search void requests" placeholder="Receipt, requester, reason" value={q} onChange={(e) => { setPage(0); setQ(e.target.value); }} />
          <Select aria-label="Status" value={status} onChange={(e) => { setPage(0); setStatus(e.target.value); }}>
            <option value="all">All statuses</option>
            <option value="pending">Pending review</option>
            <option value="returned">Returned for correction</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <div className="self-center text-xs text-text2">{total} requests</div>
        </div>
      </Card>
      {listQ.isError || listQ.data?.error ? (
        <div className="mb-3 text-sm text-err">{listQ.data?.error || "Could not load void requests."}</div>
      ) : null}
      <Card className="overflow-hidden">
        {listQ.isLoading ? <div className="py-10 text-center text-sm text-text2">Loading void requests…</div> : null}
        {!listQ.isLoading && rows.length === 0 ? (
          <div className="py-10 text-center text-sm text-text2">No void requests match this filter.</div>
        ) : (
          <div className="divide-y divide-border">
            {rows.map((row) => (
              <button
                key={row.id}
                type="button"
                className={`flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-hover ${openId === row.id ? "bg-gold/10" : ""}`}
                onClick={() => { setOpenId(row.id); setDraft(row.current_reason || ""); setMsg(""); }}
              >
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-text">{row.receipt_number || `Request #${row.id}`}</span>
                  <span className="block text-xs text-text2">{row.requested_by || "—"} · {String(row.created_at || "").replace("T", " ").slice(0, 19)}</span>
                  <span className="block text-xs font-semibold text-gold">View receipt</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block font-semibold text-gold">{KES(row.amount)}</span>
                  <Badge tone={tone(row.status) as any}>{row.status}</Badge>
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2 px-4 py-3 text-xs text-text2">
          <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <span className="self-center">Page {page + 1} / {pages}</span>
          <Button size="sm" variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      </Card>
      {openId != null ? (
        <RequestReceiptDialog
          title={event?.receipt?.receipt_number || event?.receipt_number || `Request #${openId}`}
          status={event?.status}
          reason={event?.current_reason || event?.original_reason}
          requester={event?.requested_by}
          submittedAt={event?.created_at}
          receipt={event?.receipt || (opened?.sale_id ? { id: opened.sale_id, receipt_number: opened.receipt_number, total: opened.amount } : null)}
          lines={event?.lines}
          note={event?.receipt_note}
          onClose={() => setOpenId(null)}
        >
          {detailQ.isLoading ? <div className="text-text2">Loading the receipt…</div> : null}
          {event?.error ? <div className="text-err">{event.error}</div> : null}
          {(event?.history || []).length ? (
            <div>
              <div className="font-semibold text-text">History</div>
              {event!.history!.map((item, index) => (
                <div key={index} className="text-text2">{item.action} · {item.by || "—"} · {item.note || item.reason || ""}</div>
              ))}
            </div>
          ) : null}
          {event && !event.error && !locked ? (
            <div className="space-y-2">
              <Input aria-label="Corrected reason" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Corrected reason" />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => correctM.mutate()} disabled={correctM.isPending}>Save correction</Button>
                {event.status === "returned" ? (
                  <Button size="sm" variant="primary" onClick={() => resubmitM.mutate()}>Resubmit</Button>
                ) : null}
              </div>
            </div>
          ) : null}
          {canReview && (event?.status === "pending" || event?.status === "escalated") ? (
            <div className="space-y-2">
              <Input aria-label="Review comment" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Review comment" />
              {sessionSuper ? (
                <div className="text-xs text-text2">Signed in as Super Admin. This approval does not ask for the PIN again.</div>
              ) : (
                <Input type="password" autoComplete="off" aria-label="Super-Admin PIN" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="Super-Admin PIN" />
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="primary" onClick={() => decideM.mutate("approve")}>Approve and void</Button>
                <Button size="sm" variant="secondary" onClick={() => returnM.mutate()}>Return for correction</Button>
                <Button size="sm" variant="ghost" onClick={() => decideM.mutate("reject")}>Reject</Button>
              </div>
            </div>
          ) : null}
          {msg ? <div className="text-text">{msg}</div> : null}
        </RequestReceiptDialog>
      ) : null}
    </AppShell>
  );
}
