import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Users,
  RefreshCw,
  HardDrive,
  Sparkles,
  ClipboardCheck,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, KpiCard, SectionTitle } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/live")({
  component: LivePage,
});

function LivePage() {
  const liveQ = useQuery({
    queryKey: ["live"],
    queryFn: () => GET<any>("/live"),
    refetchInterval: 20_000,
  });
  const d = liveQ.data || {};
  const sales = d.sales_today || {};
  const cashiers = Array.isArray(d.cashiers) ? d.cashiers : [];
  const users = Array.isArray(d.online_users) ? d.online_users : [];
  const syncPending = Number(d.sync?.pending || 0);
  const bak = d.backup || {};
  const ai = d.ai || {};

  return (
    <AppShell title="Live Monitoring">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-xl font-bold text-text flex items-center gap-2">
            <Activity className="h-5 w-5 text-gold" /> Live Monitoring
          </h2>
          <p className="text-sm text-text2">
            Auto-refreshes every 20s
            {d.refreshed_at ? (
              <>
                {" "}
                · last {new Date(d.refreshed_at).toLocaleTimeString("en-GB", { hour12: false })}
              </>
            ) : null}
          </p>
        </div>
        <Badge tone={liveQ.isFetching ? "info" : "ok"}>
          {liveQ.isFetching ? "Refreshing…" : "Live"}
        </Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <KpiCard
          label="Sales Today"
          value={KES(Number(sales.revenue || 0))}
          sub={`${sales.transactions || 0} receipts`}
          accent="gold"
          icon={<Activity className="h-5 w-5" />}
        />
        <KpiCard
          label="Sync Queue"
          value={String(syncPending)}
          sub="Pending items"
          accent={syncPending ? "warn" : "ok"}
          icon={<RefreshCw className="h-5 w-5" />}
        />
        <KpiCard
          label="Backup"
          value={String(bak.status || "—").toUpperCase()}
          sub={bak.created_at ? String(bak.created_at).slice(0, 16) : "No history"}
          accent={bak.status === "ok" ? "ok" : bak.status === "error" ? "err" : "warn"}
          icon={<HardDrive className="h-5 w-5" />}
        />
        <KpiCard
          label="AI Status"
          value={String(ai.label || "—")}
          sub={ai.configured ? "Configured" : "Local heuristics"}
          accent={ai.online ? "ok" : "info"}
          icon={<Sparkles className="h-5 w-5" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <Card className="p-4">
          <SectionTitle>Cashiers today</SectionTitle>
          {cashiers.length === 0 ? (
            <p className="text-sm text-text2 py-4">No cashier activity yet today.</p>
          ) : (
            <ul className="space-y-2">
              {cashiers.map((c: any, i: number) => (
                <li
                  key={i}
                  className="flex items-center justify-between gap-2 py-2 border-b border-border/50 last:border-0"
                >
                  <span className="font-medium text-text truncate">{c.name || "Unknown"}</span>
                  <span className="text-sm text-text2 tabular-nums shrink-0">
                    {c.txns} · <span className="text-gold font-semibold">{KES(c.revenue)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle
            action={
              <Link to="/users" className="text-sm text-gold font-semibold">
                Users
              </Link>
            }
          >
            Staff directory
          </SectionTitle>
          <div className="flex items-center gap-2 text-xs text-text2 mb-3">
            <Users className="h-3.5 w-3.5" /> Active accounts (by last login)
          </div>
          {users.length === 0 ? (
            <p className="text-sm text-text2 py-4">No users found.</p>
          ) : (
            <ul className="space-y-2 max-h-64 overflow-y-auto scrollbar-thin">
              {users.slice(0, 12).map((u: any) => (
                <li
                  key={u.id}
                  className="flex items-center justify-between gap-2 py-1.5 border-b border-border/40 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-text truncate">
                      {u.full_name || u.username}
                    </div>
                    <div className="text-[11px] text-text2 uppercase tracking-wide">
                      {u.role}
                    </div>
                  </div>
                  <span className="text-[11px] text-muted-fg tabular-nums shrink-0">
                    {u.last_login ? String(u.last_login).slice(0, 16) : "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-text2">
          <ClipboardCheck className="h-4 w-4 text-gold" />
          <span>
            <strong className="text-text">{d.pending_approvals || 0}</strong> pending approvals
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/approvals" className="text-sm text-gold font-semibold">
            Open Approvals →
          </Link>
          <Link to="/health" className="text-sm text-gold font-semibold">
            System Health →
          </Link>
          <Link to="/backup" className="text-sm text-gold font-semibold">
            Backup →
          </Link>
        </div>
      </Card>
    </AppShell>
  );
}
