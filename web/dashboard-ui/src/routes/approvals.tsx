import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X, Plus, Filter } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Select } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/approvals")({
  component: ApprovalsPage,
});

const TYPES = [
  "void",
  "refund",
  "large_discount",
  "price_override",
  "stock_adjust",
  "expense",
  "credit",
] as const;

type Approval = {
  id: number;
  type: string;
  title: string;
  details?: string;
  amount?: number;
  status: string;
  requested_by?: string;
  reviewed_by?: string;
  review_note?: string;
  created_at?: string;
};

function ApprovalsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("pending");
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    type: "refund",
    title: "",
    details: "",
    amount: "",
  });

  const q = useQuery({
    queryKey: ["approvals", status],
    queryFn: () =>
      GET<{ approvals: Approval[] }>(
        "/approvals",
        status === "all" ? undefined : { status },
      ),
    refetchInterval: 20_000,
  });

  const approveM = useMutation({
    mutationFn: (id: number) => POST(`/approvals/${id}/approve`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
  const rejectM = useMutation({
    mutationFn: (id: number) => POST(`/approvals/${id}/reject`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
  const createM = useMutation({
    mutationFn: () =>
      POST("/approvals", {
        type: form.type,
        title: form.title || form.type.replace(/_/g, " "),
        details: form.details,
        amount: Number(form.amount) || 0,
      }),
    onSuccess: () => {
      setShowNew(false);
      setForm({ type: "refund", title: "", details: "", amount: "" });
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  const rows = useMemo(() => {
    const list = q.data?.approvals || [];
    return Array.isArray(list) ? list : [];
  }, [q.data]);

  const tone = (s: string) =>
    s === "approved" ? "ok" : s === "rejected" ? "err" : s === "pending" ? "warn" : "muted";

  return (
    <AppShell title="Remote Approvals">
      <PageHeader
        eyebrow="Overview"
        title="Approvals Queue"
        description="Void, refund, discount, override, stock, expense & credit requests"
        actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-text2" />
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="all">All</option>
            </Select>
          </div>
          <Button variant="primary" onClick={() => setShowNew((v) => !v)}>
            <Plus className="h-4 w-4" /> New Request
          </Button>
        </div>
        }
      />

      {showNew ? (
        <Card className="p-4 mb-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase mb-1">
                Type
              </div>
              <Select
                value={form.type}
                onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
                className="w-full"
              >
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <div className="text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase mb-1">
                Amount
              </div>
              <Input
                type="number"
                placeholder="0"
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
              />
            </div>
            <div className="sm:col-span-2">
              <div className="text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase mb-1">
                Title
              </div>
              <Input
                placeholder="Short description"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              />
            </div>
            <div className="sm:col-span-2">
              <div className="text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase mb-1">
                Details
              </div>
              <Input
                placeholder="Reason / context"
                value={form.details}
                onChange={(e) => setForm((f) => ({ ...f, details: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="primary"
              disabled={createM.isPending}
              onClick={() => createM.mutate()}
            >
              Submit
            </Button>
            <Button variant="ghost" onClick={() => setShowNew(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {q.isLoading ? (
        <div className="py-12 text-center text-sm text-text2">Loading approvals…</div>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            title="No approvals"
            description={
              status === "pending"
                ? "No pending requests. Create one or wait for remote cashier actions."
                : "Nothing in this filter."
            }
          />
        </Card>
      ) : (
        <>
          {/* Desktop table */}
          <Card className="hidden md:block overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b border-border bg-panel/40">
                    {["Type", "Title", "Amount", "By", "Status", "Actions"].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-2.5 text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.id} className="border-b border-border/60 hover:bg-hover/40">
                      <td className="px-4 py-3 text-text2 capitalize">
                        {a.type.replace(/_/g, " ")}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-text">{a.title}</div>
                        {a.details ? (
                          <div className="text-xs text-text2 truncate max-w-xs">{a.details}</div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-gold font-semibold">
                        {KES(Number(a.amount || 0))}
                      </td>
                      <td className="px-4 py-3 text-text2">{a.requested_by || "—"}</td>
                      <td className="px-4 py-3">
                        <Badge tone={tone(a.status) as any}>{a.status}</Badge>
                      </td>
                      <td className="px-4 py-3">
                        {a.status === "pending" ? (
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="success"
                              disabled={approveM.isPending}
                              onClick={() => approveM.mutate(a.id)}
                            >
                              <Check className="h-3.5 w-3.5" /> Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              disabled={rejectM.isPending}
                              onClick={() => rejectM.mutate(a.id)}
                            >
                              <X className="h-3.5 w-3.5" /> Reject
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-text2">
                            {a.reviewed_by || "—"}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {rows.map((a) => (
              <Card key={a.id} className="p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <div className="text-[10px] tracking-[0.16em] uppercase text-text2 font-semibold">
                      {a.type.replace(/_/g, " ")}
                    </div>
                    <div className="font-semibold text-text">{a.title}</div>
                  </div>
                  <Badge tone={tone(a.status) as any}>{a.status}</Badge>
                </div>
                {a.details ? <p className="text-sm text-text2 mb-2">{a.details}</p> : null}
                <div className="flex items-center justify-between text-sm mb-3">
                  <span className="text-gold font-bold tabular-nums">
                    {KES(Number(a.amount || 0))}
                  </span>
                  <span className="text-text2 text-xs">{a.requested_by || "—"}</span>
                </div>
                {a.status === "pending" ? (
                  <div className="flex gap-2">
                    <Button
                      className="flex-1 min-h-[44px]"
                      variant="success"
                      onClick={() => approveM.mutate(a.id)}
                    >
                      <Check className="h-4 w-4" /> Approve
                    </Button>
                    <Button
                      className="flex-1 min-h-[44px]"
                      variant="danger"
                      onClick={() => rejectM.mutate(a.id)}
                    >
                      <X className="h-4 w-4" /> Reject
                    </Button>
                  </div>
                ) : null}
              </Card>
            ))}
          </div>
        </>
      )}
    </AppShell>
  );
}
