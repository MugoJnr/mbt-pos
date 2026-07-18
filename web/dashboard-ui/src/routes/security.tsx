import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, Lock, KeyRound, ScrollText } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, Input, PageHeader, SectionTitle, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/security")({
  component: Security,
});

function Security() {
  const [q, setQ] = useState("");
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const auditQ = useQuery({
    queryKey: ["audit"],
    queryFn: () => GET<any[]>("/audit"),
  });

  const s = settingsQ.data || {};
  const pinMin = s.pin_min_length || s.min_pin_length || "6";
  const sessionMin = s.session_timeout_minutes || s.auto_lock_minutes || "15";
  const lockout = s.failed_login_lockout || "5";
  const rotation = s.password_rotation_days || "90";

  const logs = useMemo(() => {
    const raw = Array.isArray(auditQ.data) ? auditQ.data : [];
    if (!q.trim()) return raw.slice(0, 100);
    const needle = q.toLowerCase();
    return raw
      .filter((l) =>
        [l.action, l.module, l.username, l.details, l.created_at]
          .map((x) => String(x || "").toLowerCase())
          .some((t) => t.includes(needle)),
      )
      .slice(0, 100);
  }, [auditQ.data, q]);

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
              and audit trail for managers.
            </p>
          </div>
        </Card>

        <Card className="p-5">
          <SectionTitle>Notes</SectionTitle>
          <ul className="space-y-2 text-sm text-text2">
            <li>Audit access requires manager or admin role.</li>
            <li>Privileged actions (voids, settings, user changes) appear below.</li>
            <li>Force session lock and PIN rotation remain desktop Superadmin tools.</li>
          </ul>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="p-4 border-b border-border flex flex-wrap items-center justify-between gap-2">
          <SectionTitle>Audit log</SectionTitle>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter action, user, module…"
            className="max-w-xs min-h-[40px]"
          />
        </div>
        {auditQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading audit…</div>
        ) : err ? (
          <div className="py-12 text-center text-sm text-err">{String(err)}</div>
        ) : (
          <Table head={["When", "User", "Action", "Module", "Details"]}>
            {logs.map((l: any, i: number) => (
              <tr key={l.id || i}>
                <td className="px-4 py-2.5 text-xs text-text2 tabular-nums whitespace-nowrap">
                  {(l.created_at || "").toString().slice(0, 19)}
                </td>
                <td className="px-4 py-2.5 text-text">{l.username || l.user || "system"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-gold">{l.action}</td>
                <td className="px-4 py-2.5 text-text2">{l.module || "—"}</td>
                <td className="px-4 py-2.5 text-text2 text-xs max-w-[280px] truncate">
                  {l.details || l.description || "—"}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </AppShell>
  );
}
