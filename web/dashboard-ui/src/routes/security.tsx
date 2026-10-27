import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, Lock, KeyRound, ScrollText } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/security")({
  component: Security,
});

function Security() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<number | null>(() => {
    const match = window.location.hash.match(/^#audit-(\d+)$/);
    return match ? Number(match[1]) : null;
  });
  const [currentPin, setCurrentPin] = useState("");
  const [newPin, setNewPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [pinMsg, setPinMsg] = useState("");
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const auditQ = useQuery({
    queryKey: ["audit", q, page],
    queryFn: () => GET<any[]>("/audit", { q, limit: "50", offset: String(page * 50) }),
  });
  const detailQ = useQuery({
    queryKey: ["audit-event", openId],
    queryFn: () => GET<any>(`/audit/${openId}`),
    enabled: openId != null,
  });

  const s = settingsQ.data || {};
  const pinMin = s.pin_min_length || s.min_pin_length || "6";
  const sessionMin = s.session_timeout_minutes || s.auto_lock_minutes || "15";
  const lockout = s.failed_login_lockout || "5";
  const rotation = s.password_rotation_days || "90";

  const logs = useMemo(() => (Array.isArray(auditQ.data) ? auditQ.data : []), [auditQ.data]);

  function openEvent(id: number) {
    setOpenId(id);
    window.location.hash = `audit-${id}`;
  }

  function closeEvent() {
    setOpenId(null);
    if (window.location.hash.startsWith("#audit-")) {
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }

  const err =
    auditQ.data && !Array.isArray(auditQ.data) ? (auditQ.data as any).error : null;

  return (
    <AppShell title="Security">
      <PageHeader
        eyebrow="Admin"
        title="Security"
        description="Policy settings from the POS database and live audit trail."
        icon={<ShieldCheck className="h-5 w-5 text-gold" />}
      />
      <Card className="mb-4 p-4">
        <div className="text-sm font-semibold text-text">Super-Admin PIN</div>
        <p className="mt-1 text-xs text-text2">
          This is not the login password. Leave the current PIN blank only when no PIN has been set.
          A stock reduction and a void use this PIN.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <Input type="password" value={currentPin} onChange={(e) => setCurrentPin(e.target.value)} placeholder="Current PIN" />
          <Input type="password" value={newPin} onChange={(e) => setNewPin(e.target.value)} placeholder="New PIN, 6 digits" />
          <Input type="password" value={confirmPin} onChange={(e) => setConfirmPin(e.target.value)} placeholder="Confirm PIN" />
        </div>
        <Button
          className="mt-3"
          onClick={async () => {
            setPinMsg("");
            const res = await POST<any>("/account/pin", {
              current_pin: currentPin,
              new_pin: newPin,
              confirm_pin: confirmPin,
            });
            if (res?.success) {
              setPinMsg("Super-Admin PIN saved.");
              setCurrentPin("");
              setNewPin("");
              setConfirmPin("");
            } else {
              setPinMsg(res?.error || "Could not save the PIN.");
            }
          }}
        >
          Save PIN
        </Button>
        {pinMsg ? <div className="mt-2 text-sm text-text2">{pinMsg}</div> : null}
      </Card>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {[
          {
            k: "PIN Policy",
            v: `Min ${pinMin}`,
            tone: "ok" as const,
            i: <KeyRound className="h-5 w-5" />,
          },
          {
            k: "Session / Auto-Lock",
            v: `${sessionMin} min`,
            tone: "info" as const,
            i: <Lock className="h-5 w-5" />,
          },
          {
            k: "Audit Log",
            v: Array.isArray(auditQ.data) ? `${auditQ.data.length} rows` : "…",
            tone: "ok" as const,
            i: <ScrollText className="h-5 w-5" />,
          },
        ].map((row) => (
          <Card key={row.k} className="p-5 flex items-center gap-4">
            <div className="h-11 w-11 rounded-md grid place-items-center bg-gold/15 text-gold">
              {row.i}
            </div>
            <div className="flex-1">
              <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">
                {row.k}
              </div>
              <div className="text-xl font-bold text-text mt-0.5">{row.v}</div>
            </div>
            <Badge tone={row.tone}>Live</Badge>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card className="p-5">
          <SectionTitle>Policy (read from settings)</SectionTitle>
          <div className="space-y-3 text-sm">
            {[
              ["Minimum PIN length", pinMin],
              ["Password rotation (days)", rotation],
              ["Failed attempts before lockout", lockout],
              ["Session timeout (minutes)", sessionMin],
            ].map(([l, v]) => (
              <div key={l} className="flex items-center justify-between gap-4 py-2 border-b border-border/50">
                <span className="text-text2">{l}</span>
                <span className="font-semibold text-text tabular-nums">{v}</span>
              </div>
            ))}
            <p className="text-xs text-text2 pt-2">
              Change PIN / lock policy from the desktop Security tab. Web shows the effective values
              and the audit trail.
            </p>
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle>Notes</SectionTitle>
          <ul className="space-y-2 text-sm text-text2">
            <li>Audit records can be opened by an Admin or Super Admin. They cannot be edited here.</li>
            <li>Privileged actions (voids, settings, user changes) appear below.</li>
            <li>The Super-Admin PIN can be changed on this page. It is not the login password.</li>
          </ul>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="p-4 border-b border-border flex flex-wrap items-center justify-between gap-2">
          <SectionTitle>Audit log</SectionTitle>
          <Input
            value={q}
            onChange={(e) => {
              setPage(0);
              setQ(e.target.value);
            }}
            placeholder="Search action, user, module…"
            className="max-w-xs min-h-[40px]"
          />
        </div>
        {openId != null ? (
          <AuditDetail
            loading={detailQ.isLoading}
            error={detailQ.data?.error || (detailQ.error ? "The audit event could not be loaded." : "")}
            event={detailQ.data?.error ? null : detailQ.data}
            onClose={closeEvent}
            onOpen={openEvent}
          />
        ) : null}
        {auditQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading audit…</div>
        ) : err ? (
          <div className="py-12 text-center text-sm text-err">{String(err)}</div>
        ) : (
          <>
          <Table head={["When", "User", "Action", "Module", "Details"]}>
            {logs.length === 0 ? (
              <tr><td className="px-4 py-4 text-text2" colSpan={5}>No audit events match this search.</td></tr>
            ) : null}
            {logs.map((l: any) => (
              <tr
                key={l.id}
                className="cursor-pointer hover:bg-hover"
                onClick={() => openEvent(Number(l.id))}
                onKeyDown={(event) => {
                  if (event.key === "Enter") openEvent(Number(l.id));
                }}
                tabIndex={0}
                aria-label={`Open audit event ${l.id}`}
              >
                <td className="px-4 py-2.5 text-xs text-text2 tabular-nums whitespace-nowrap">
                  {(l.created_at || "").toString().slice(0, 19)}
                </td>
                <td className="px-4 py-2.5 text-text">{l.username || "Not recorded"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-gold">{l.action}</td>
                <td className="px-4 py-2.5 text-text2">{l.module || "—"}</td>
                <td className="px-4 py-2.5 text-text2 text-xs max-w-[280px] truncate">
                  {l.details || "—"}
                </td>
              </tr>
            ))}
          </Table>
          <div className="flex items-center justify-end gap-2 p-3">
            <Button variant="secondary" disabled={page === 0} onClick={() => setPage((n) => Math.max(0, n - 1))}>Previous</Button>
            <span className="text-xs text-text2">Page {page + 1}</span>
            <Button variant="secondary" disabled={logs.length < 50} onClick={() => setPage((n) => n + 1)}>Next</Button>
          </div>
          </>
        )}
      </Card>
    </AppShell>
  );
}

function AuditDetail({
  event,
  loading,
  error,
  onClose,
  onOpen,
}: {
  event: any;
  loading: boolean;
  error: string;
  onClose: () => void;
  onOpen: (id: number) => void;
}) {
  return (
    <div className="border-b border-border bg-panel/40 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-text">Audit event</div>
        <Button variant="secondary" onClick={onClose}>Close</Button>
      </div>
      {loading ? <div className="text-sm text-text2">Loading this event…</div> : null}
      {error ? <div className="text-sm text-err">{error}</div> : null}
      {event && !loading ? (
        <div className="space-y-4 text-sm">
          <div className="grid gap-2 sm:grid-cols-2">
            <Fact label="Event ID" value={event.id} />
            <Fact label="Action" value={event.action} />
            <Fact label="Area" value={event.module} />
            <Fact label="Outcome" value={event.outcome} />
            <Fact label="User" value={event.username} />
            <Fact label="User ID" value={event.user_id ?? "Not recorded"} />
            <Fact label="Role at the time" value={event.role_at_event} />
            <Fact label="Source" value={event.source} />
            <Fact label="Request address" value={event.ip_address} />
            <Fact label="Recorded" value={event.recorded_at} />
            <Fact label="When it happened" value={event.occurred_at} />
            <Fact label="Synchronized" value={event.synced_at} />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-text2">What was recorded</div>
            <p className="mt-1 whitespace-pre-wrap break-words text-text">{event.details}</p>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-text2">Before and after</div>
            {event.changes?.length ? (
              <div className="mt-2 space-y-2">
                {event.changes.map((change: any) => (
                  <div key={change.field} className="rounded-lg border border-border px-3 py-2">
                    <div className="font-semibold text-text">{change.field}</div>
                    <div className="text-text2">Before: {change.before}</div>
                    <div className="text-text">After: {change.after}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-text2">This event did not record a before-and-after value.</p>
            )}
          </div>
          {event.linked ? (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-text2">Linked record now</div>
              <p className="mt-1 text-text2">{event.linked.note}</p>
              {event.linked.available && event.linked.kind === "product" ? (
                <div className="mt-1 grid gap-1 sm:grid-cols-2">
                  <Fact label="Product" value={event.linked.record.name} />
                  <Fact label="SKU" value={event.linked.record.sku || "Not recorded"} />
                  <Fact label="Current price" value={event.linked.record.price} />
                  <Fact label="Current stock" value={event.linked.record.stock} />
                  <Fact label="Status now" value={Number(event.linked.record.is_active) ? "Active" : "Archived"} />
                </div>
              ) : null}
              {event.linked.available && event.linked.kind === "receipt" ? (
                <div className="mt-1 grid gap-1 sm:grid-cols-2">
                  <Fact label="Receipt" value={event.linked.record.receipt_number} />
                  <Fact label="Current total" value={event.linked.record.total} />
                  <Fact label="Payment" value={event.linked.record.payment_method} />
                  <Fact label="Status now" value={event.linked.record.status} />
                  <Fact label="Business date" value={event.linked.record.sale_date || "Not recorded"} />
                  <Fact label="Posted" value={event.linked.record.created_at || "Not recorded"} />
                </div>
              ) : null}
              {event.linked && !event.linked.available ? (
                <p className="mt-1 text-text">The linked record is not in this shop.</p>
              ) : null}
            </div>
          ) : null}
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-text2">Related events</div>
            {event.related?.length ? (
              <ul className="mt-1 space-y-1">
                {event.related.map((item: any) => (
                  <li key={item.id}>
                    <button type="button" className="text-left text-gold hover:underline" onClick={() => onOpen(item.id)}>
                      #{item.id} {item.action} · {item.username} · {String(item.created_at || "").slice(0, 19)}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-text2">No other event shares a recorded product or receipt reference.</p>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text2">{label}</div>
      <div className="break-words text-text">{String(value ?? "Not recorded")}</div>
    </div>
  );
}
