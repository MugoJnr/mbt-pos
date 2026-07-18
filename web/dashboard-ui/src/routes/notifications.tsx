import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  AlertTriangle,
  ShoppingCart,
  RefreshCw,
  HardDrive,
  Shield,
  Package,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/notifications")({
  component: NotificationsPage,
});

type Notif = {
  id: number;
  type: string;
  title: string;
  body?: string;
  severity?: string;
  is_read?: number;
  link?: string;
  created_at?: string;
};

const ICONS: Record<string, typeof Bell> = {
  low_stock: Package,
  large_sale: ShoppingCart,
  refund: RefreshCw,
  backup: HardDrive,
  sync: RefreshCw,
  security: Shield,
};

function NotificationsPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () =>
      GET<{ notifications: Notif[]; unread: number }>("/notifications", { limit: "80" }),
    refetchInterval: 15_000,
  });
  const readAll = useMutation({
    mutationFn: () => POST("/notifications/read-all", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notifications-badge"] });
    },
  });
  const readOne = useMutation({
    mutationFn: (id: number) => POST(`/notifications/${id}/read`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notifications-badge"] });
    },
  });

  const rows = q.data?.notifications || [];
  const unread = Number(q.data?.unread || 0);

  const tone = (s?: string) =>
    s === "err" || s === "error"
      ? "err"
      : s === "warn"
        ? "warn"
        : s === "ok"
          ? "ok"
          : "info";

  return (
    <AppShell title="Notifications">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-xl font-bold text-text flex items-center gap-2">
            <Bell className="h-5 w-5 text-gold" /> Notifications
          </h2>
          <p className="text-sm text-text2">
            {unread} unread · polls every 15s
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={!unread || readAll.isPending}
          onClick={() => readAll.mutate()}
        >
          Mark all read
        </Button>
      </div>

      {q.isLoading ? (
        <div className="py-12 text-center text-sm text-text2">Loading…</div>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<AlertTriangle className="h-8 w-8 text-muted-fg" />}
            title="No notifications yet"
            description="Low stock, large sales, backup and sync events will appear here."
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((n) => {
            const Icon = ICONS[n.type] || Bell;
            const unreadRow = !n.is_read;
            return (
              <Card
                key={n.id}
                className={`p-3 sm:p-4 ${unreadRow ? "border-gold/40 bg-gold/5" : ""}`}
              >
                <div className="flex gap-3">
                  <div className="h-10 w-10 shrink-0 rounded-full bg-panel grid place-items-center">
                    <Icon className="h-4 w-4 text-gold" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 mb-0.5">
                      <span className="font-semibold text-text">{n.title}</span>
                      <Badge tone={tone(n.severity) as any}>{n.type}</Badge>
                      {unreadRow ? <Badge tone="gold">New</Badge> : null}
                    </div>
                    {n.body ? <p className="text-sm text-text2">{n.body}</p> : null}
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-fg">
                      <span className="font-mono">
                        {n.created_at ? String(n.created_at).replace("T", " ").slice(0, 19) : ""}
                      </span>
                      {n.link ? (
                        <Link to={n.link as any} className="text-gold font-semibold">
                          Open →
                        </Link>
                      ) : null}
                      {unreadRow ? (
                        <button
                          type="button"
                          className="text-gold font-semibold min-h-[32px]"
                          onClick={() => readOne.mutate(n.id)}
                        >
                          Mark read
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
