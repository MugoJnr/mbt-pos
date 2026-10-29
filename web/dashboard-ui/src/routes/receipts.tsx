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
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [voidMsg, setVoidMsg] = useState("");
  const [voiding, setVoiding] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestReason, setRequestReason] = useState("");
  const [requestMsg, setRequestMsg] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [copyMsg, setCopyMsg] = useState("");
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
  const storedStatus = String(header.status || "").toLowerCase();
  const shownStatus = storedStatus === "voided"
    ? "voided"
    : storedStatus === "completed"
      ? "completed"
      : String(header.display_status || open?.display_status || header.status || (Number(header.voided || 0) === 1 ? "voided" : open?.status) || "");
  const canVoidNow = user?.role === "superadmin" && open?.kind === "sale" && storedStatus === "completed";
  const canRequestVoid = Boolean(open && open.kind === "sale" && storedStatus === "completed" && user?.role && !["superadmin", "viewer"].includes(user.role));
  const tenders = Array.isArray(detailQ.data?.tenders) ? detailQ.data.tenders : [];
  const paidWith = Array.from(new Set(
    tenders
      .filter((tender: any) => String(tender?.status || "confirmed").toLowerCase() === "confirmed")
      .map((tender: any) => String(tender?.method || "").trim())
      .filter((name: string) => name && !["credit", "account"].includes(name.toLowerCase()))
  )).join(" + ");
  const customer = detailQ.data?.customer;
  const debt = detailQ.data?.debt;
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
              <tr key={`${row.kind}-${row.id}`} className="cursor-pointer" onClick={() => setOpen(row)}>
                <td className="px-4 py-2.5 text-text2">{String(row.at || "").replace("T", " ").slice(0, 19)}</td>
                <td className="px-4 py-2.5">{row.kind.replace(/_/g, " ")}</td>
                <td className="px-4 py-2.5 font-semibold text-text">{row.reference}</td>
                <td className="px-4 py-2.5">{row.user || "—"}</td>
                <td className="px-4 py-2.5 tabular-nums">{row.amount == null ? "—" : KES(row.amount)}</td>
                <td className="px-4 py-2.5">{row.payment || "—"}</td>
                <td className="px-4 py-2.5"><Badge tone={(row.display_status || row.status) === "voided" ? "err" : (row.display_status || row.status) === "pending" ? "warn" : "ok"}>{row.display_status || row.status}</Badge></td>
                <td className="px-4 py-2.5">
                  <Button size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); setOpen(row); }}>Open</Button>
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
                  <div className="flex items-center gap-2">
                    <div className="select-all text-lg font-extrabold text-text">{detailQ.data?.reference || open.reference}</div>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        const reference = String(detailQ.data?.reference || open.reference || "").trim();
                        if (!reference) {
                          setCopyMsg("There is no reference to copy.");
                          return;
                        }
                        try {
                          await navigator.clipboard.writeText(reference);
                          setCopyMsg("Copied");
                        } catch {
                          const area = document.createElement("textarea");
                          area.value = reference;
                          area.setAttribute("readonly", "true");
                          document.body.appendChild(area);
                          area.select();
                          const copied = document.execCommand("copy");
                          area.remove();
                          setCopyMsg(copied ? "Copied" : "Could not copy");
                        }
                      }}
                    >
                      Copy reference
                    </Button>
                  </div>
                  {copyMsg ? <div className="text-xs text-text2">{copyMsg}</div> : null}
                </div>
                <Button variant="ghost" onClick={() => { setCopyMsg(""); setOpen(null); }}>Close</Button>
              </div>
              {detailQ.isLoading ? <div className="text-sm text-text2">Loading…</div> : null}
              {detailQ.data?.error ? <div className="text-sm text-err">{detailQ.data.error}</div> : null}
              <p className="mb-3 text-sm text-text2">{open.summary}</p>
              <div className="mb-3 grid grid-cols-2 gap-2 text-sm">
                <div>Status <span className="font-semibold text-text">{shownStatus || "—"}</span></div>
                <div>User <span className="font-semibold text-text">{header.cashier_name || header.username || header.created_by_name || open.user || "—"}</span></div>
                <div>Payment <span className="font-semibold text-text">{paidWith || header.payment_method || open.payment || "—"}</span></div>
                <div>Total <span className="font-semibold text-text">{header.total == null && open.amount == null ? "—" : KES(header.total ?? open.amount)}</span></div>
              </div>
              {customer ? (
                <p className="mb-2 text-sm text-text">Customer {customer.name}{customer.phone ? ` · ${customer.phone}` : ""}</p>
              ) : null}
              {tenders.length ? (
                <div className="mb-3 text-sm">
                  <div className="font-semibold text-text">Tenders</div>
                  {tenders.map((tender: any, index: number) => (
                    <div key={index} className="text-text2">
                      {tender.method} · {KES(tender.amount)}{tender.status ? ` · ${tender.status}` : ""}
                    </div>
                  ))}
                </div>
              ) : null}
              {debt ? (
                <p className="mb-3 text-sm text-text">
                  Debt {debt.invoice_number} · balance {KES(debt.balance)} · {debt.status}
                </p>
              ) : null}
              <div className="mb-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    const reference = detailQ.data?.reference || open.reference;
                    const popup = window.open("", "mbt-receipt", "noopener,width=480,height=720");
                    if (!popup) return;
                    const itemRows = lines.map((line: any) => `<tr><td>${line.product_name || line.name || ""}</td><td>${line.quantity}</td><td>${line.unit_price ?? ""}</td><td>${line.total ?? ""}</td></tr>`).join("");
                    const tenderRows = tenders.map((tender: any) => `<div>${tender.method} ${tender.amount}${tender.status ? " (" + tender.status + ")" : ""}</div>`).join("");
                    popup.document.write(`<!doctype html><html><head><title>${reference}</title><style>body{font-family:Segoe UI,sans-serif;padding:24px;color:#111}table{width:100%;border-collapse:collapse}td{padding:4px 0;border-bottom:1px solid #ddd}</style></head><body><h1>${reference}</h1><p>${shownStatus || ""} · ${header.cashier_name || header.username || open.user || ""}</p><p>${paidWith || header.payment_method || open.payment || ""}</p>${customer ? `<p>${customer.name}</p>` : ""}${tenderRows}<table>${itemRows}</table><p><strong>Total ${header.total ?? open.amount ?? ""}</strong></p>${debt ? `<p>Debt ${debt.invoice_number} balance ${debt.balance}</p>` : ""}<p>Reprint of the saved receipt. This does not create a new sale.</p></body></html>`);
                    popup.document.close();
                    popup.focus();
                    popup.print();
                  }}
                >
                  Print
                </Button>
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
              {canRequestVoid ? (
                <div className="mt-4">
                  <Button variant="secondary" onClick={() => { setRequestOpen(true); setRequestMsg(""); }}>Request void</Button>
                  {requestOpen ? (
                    <div className="mt-3 rounded-lg border border-border p-3">
                      <div className="text-sm font-semibold text-text">Ask for this receipt to be voided</div>
                      <p className="mt-1 text-xs text-text2">The sale stays completed until a reviewer accepts the request.</p>
                      <Input className="mt-2" aria-label="Reason for the void request" placeholder="Reason" value={requestReason} onChange={(e) => setRequestReason(e.target.value)} />
                      {requestMsg ? <div className="mt-2 text-sm text-text">{requestMsg}</div> : null}
                      <div className="mt-2 flex gap-2">
                        <Button
                          disabled={requesting}
                          onClick={async () => {
                            if (requestReason.trim().length < 3) {
                              setRequestMsg("Enter a reason before requesting a void.");
                              return;
                            }
                            setRequesting(true);
                            try {
                              const data = await POST<any>("/sales/void-request", { sale_id: open.id, reason: requestReason.trim() });
                              if (!data || data.error || data.success === false) {
                                setRequestMsg(data?.error || "The request was not saved.");
                                return;
                              }
                              setRequestMsg(data.duplicate ? "This request is already open." : "Request saved. The receipt is still completed.");
                              setRequestOpen(false);
                              qc.invalidateQueries({ queryKey: ["receipt", open.kind, open.id] });
                            } finally {
                              setRequesting(false);
                            }
                          }}
                        >
                          {requesting ? "Sending…" : "Send request"}
                        </Button>
                        <Button variant="ghost" onClick={() => setRequestOpen(false)}>Cancel</Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
              {canVoidNow ? (
                <div className="mt-4">
                  <Button variant="secondary" onClick={() => { setVoidOpen(true); setVoidMsg(""); }}>Void Receipt</Button>
                  {voidOpen ? (
                    <div className="mt-3 rounded-lg border border-err/40 p-3">
                      <div className="text-sm font-semibold text-text">Void this receipt now</div>
                      <p className="mt-1 text-xs text-text2">
                        {header.receipt_number || open.reference} · {KES(header.total ?? open.amount)} · {shownStatus || header.status}. No request is created.
                      </p>
                      <Input className="mt-2" aria-label="Reason for voiding this receipt" placeholder="Reason" value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />
                      {voidMsg ? <div className="mt-2 text-sm text-text">{voidMsg}</div> : null}
                      <div className="mt-2 flex gap-2">
                        <Button
                          disabled={voiding}
                          onClick={async () => {
                            if (voidReason.trim().length < 3) {
                              setVoidMsg("Enter a reason before voiding this receipt.");
                              return;
                            }
                            setVoiding(true);
                            try {
                              const data = await POST<any>(`/sales/${open.id}/void-now`, { reason: voidReason.trim() });
                              if (!data || data.error || data.success === false) {
                                setVoidMsg(data?.message || data?.error || "The receipt was not voided.");
                                return;
                              }
                              setVoidMsg("Receipt voided.");
                              setVoidOpen(false);
                              qc.invalidateQueries({ queryKey: ["receipts"] });
                              qc.invalidateQueries({ queryKey: ["receipt", open.kind, open.id] });
                            } finally {
                              setVoiding(false);
                            }
                          }}
                        >
                          {voiding ? "Voiding…" : "Confirm void"}
                        </Button>
                        <Button variant="ghost" onClick={() => setVoidOpen(false)}>Cancel</Button>
                      </div>
                    </div>
                  ) : null}
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
                      Request {item.type} #{item.id} · {item.status} · {item.current_reason || item.details || item.title}
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
