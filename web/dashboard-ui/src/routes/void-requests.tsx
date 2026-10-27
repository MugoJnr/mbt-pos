import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Select } from "@/components/ui-kit";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/void-requests")({
  component: VoidRequestsPage,
});

type VoidRequest = {
  id: number;
  receipt_number?: string;
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
  receipt?: { receipt_number?: string; status?: string; total?: number; cashier_name?: string } | null;
  receipt_note?: string;
  lines?: { product_name?: string; quantity?: number; unit_price?: number; total?: number }[];
  error?: string;
};

function VoidRequestsPage() {
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const canReview = ["manager", "admin", "superadmin"].includes(role);
  const qc = useQueryClient();
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
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
    mutationFn: (action: "approve" | "reject") =>
      POST<any>(`/approvals/${openId}/${action}`, action === "approve" ? { pin: "" } : { note }),
    onSuccess: async (data) => {
      setMsg(data?.error || data?.message || "Review saved.");
      if (!data?.error) await refresh();
    },
  });

  const rows = listQ.data?.requests || [];
  const total = Number(listQ.data?.total || 0);
  const pages = Math.max(1, Math.ceil(total / limit));
  const event = detailQ.data;
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
                className="grid w-full grid-cols-1 gap-1 px-4 py-3 text-left hover:bg-hover sm:grid-cols-4"
                onClick={() => { setOpenId(row.id); setDraft(row.current_reason || ""); setMsg(""); }}
              >
                <span className="font-semibold text-text">#{row.id} · {row.receipt_number || "Receipt"}</span>
                <span className="text-sm text-text2">{row.requested_by || "—"} · {String(row.created_at || "").replace("T", " ").slice(0, 19)}</span>
                <span className="text-sm text-text2">{KES(row.amount)}</span>
                <Badge tone={tone(row.status) as any}>{row.status}</Badge>
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
        <Card className="mt-4 p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <div className="text-lg font-extrabold text-text">Request #{openId}</div>
              <div className="text-sm text-text2">{event?.status || "Loading…"}</div>
            </div>
            <Button variant="ghost" onClick={() => setOpenId(null)}>Close</Button>
          </div>
          {detailQ.isLoading ? <div className="text-sm text-text2">Loading request…</div> : null}
          {event?.error ? <div className="text-sm text-err">{event.error}</div> : null}
          {event && !event.error ? (
            <div className="space-y-3 text-sm">
              <div>Receipt <span className="font-semibold text-text">{event.receipt?.receipt_number || event.receipt_number || "—"}</span></div>
              <div>Receipt status <span className="font-semibold text-text">{event.receipt?.status || "—"}</span></div>
              <div>Total <span className="font-semibold text-text">{KES(event.receipt?.total ?? event.amount)}</span></div>
              <div>Requested by <span className="font-semibold text-text">{event.requested_by || "—"}</span> at {String(event.created_at || "").replace("T", " ").slice(0, 19)}</div>
              <div>Original reason <span className="text-text">{event.original_reason || "—"}</span></div>
              <div>Current reason <span className="text-text">{event.current_reason || "—"}</span></div>
              <div>Reviewer <span className="text-text">{event.reviewed_by || "Not reviewed"}</span></div>
              <div>Review comment <span className="text-text">{event.review_note || "None"}</span></div>
              {event.receipt_note ? <div className="text-err">{event.receipt_note}</div> : null}
              {(event.lines || []).length ? (
                <div>
                  {event.lines!.map((line, index) => (
                    <div key={index} className="text-text2">{line.product_name} · {line.quantity} · {KES(line.total)}</div>
                  ))}
                </div>
              ) : null}
              {(event.history || []).length ? (
                <div>
                  <div className="font-semibold text-text">History</div>
                  {event.history!.map((item, index) => (
                    <div key={index} className="text-text2">{item.action} · {item.by || "—"} · {item.note || item.reason || ""}</div>
                  ))}
                </div>
              ) : null}
              {!locked ? (
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
              {canReview && (event.status === "pending" || event.status === "escalated") ? (
                <div className="space-y-2">
                  <Input aria-label="Review comment" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Review comment" />
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="primary" onClick={() => decideM.mutate("approve")}>Approve and void</Button>
                    <Button size="sm" variant="secondary" onClick={() => returnM.mutate()}>Return for correction</Button>
                    <Button size="sm" variant="ghost" onClick={() => decideM.mutate("reject")}>Reject</Button>
                  </div>
                </div>
              ) : null}
              {msg ? <div className="text-text">{msg}</div> : null}
            </div>
          ) : null}
        </Card>
      ) : null}
    </AppShell>
  );
}
