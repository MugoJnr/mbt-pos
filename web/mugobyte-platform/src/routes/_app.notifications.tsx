import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCircle2, ShieldAlert, TriangleAlert, RefreshCw } from "lucide-react";
import { PageShell, PageHeader, EmptyState } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GET, POST } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/notifications")({
  component: NotificationsPage,
  head: () => ({ meta: [{ title: "Notifications | MugoByte" }] }),
});

type Notification = {
  id: string | number;
  type?: string;
  title: string;
  body?: string;
  severity?: string;
  is_read?: number | boolean;
  read_at?: string | null;
  link?: string;
  created_at: string;
};

const SEV_ICON: Record<string, typeof Bell> = {
  success: CheckCircle2,
  info: Bell,
  warning: TriangleAlert,
  error: ShieldAlert,
};

function NotificationsPage() {
  const qc = useQueryClient();
  const { orgId } = useAuth();

  const notifQ = useQuery({
    queryKey: ["cloud-notifications", orgId],
    queryFn: () =>
      GET<{ notifications?: Notification[]; unread?: number }>(
        "/cloud/v1/notifications",
        orgId ? { org_id: orgId } : undefined,
      ),
    refetchInterval: 30_000,
  });

  const markAllMut = useMutation({
    mutationFn: () => POST("/notifications/read-all"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cloud-notifications"] }),
  });

  const items = notifQ.data?.notifications || [];
  const unread =
    notifQ.data?.unread ??
    items.filter((n) => !n.is_read && !n.read_at).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Shared Service"
        title="Notification Center"
        description="Cloud alerts for licenses, devices, backups and updates. Live shop toasts remain on the Live Dashboard."
        actions={
          <>
            <Button variant="outline" onClick={() => notifQ.refetch()}>
              <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
            </Button>
            {unread > 0 && (
              <Button variant="outline" onClick={() => markAllMut.mutate()} disabled={markAllMut.isPending}>
                Mark all read
              </Button>
            )}
          </>
        }
      />

      {unread > 0 && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
          {unread} unread notification{unread !== 1 ? "s" : ""}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="font-display">History</CardTitle>
          <CardDescription>Every event is stored. Email delivery uses Resend when configured. Telegram is permanently removed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {items.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="No cloud notifications yet"
              description="License, device, backup, and update alerts will land here when they fire."
            />
          ) : (
            items.map((n) => {
              const sev = (n.severity || "info").toLowerCase();
              const Icon = SEV_ICON[sev] || Bell;
              const read = Boolean(n.is_read || n.read_at);
              return (
                <div
                  key={String(n.id)}
                  className={`flex gap-3 rounded-xl border p-3 ${read ? "border-border/50 opacity-70" : "border-border"}`}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{n.title}</span>
                      <Badge variant="secondary">{sev}</Badge>
                    </div>
                    {n.body ? <p className="mt-1 text-sm text-muted-foreground">{n.body}</p> : null}
                    <p className="mt-1 text-xs text-muted-foreground">{(n.created_at || "").toString().slice(0, 19)}</p>
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
