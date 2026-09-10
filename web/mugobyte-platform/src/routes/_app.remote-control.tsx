import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Radio,
  RefreshCw,
  MonitorSmartphone,
  Package,
  Warehouse,
  UserCog,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { useMemo, useState } from "react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  isCloudDeviceOnline,
  listCloudCommands,
  listCloudDevices,
  remoteOpsAdjustStock,
  remoteOpsSetUserActive,
  remoteOpsUpdateProduct,
  type CloudDevice,
  type RemoteCommandRow,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canManageOrganization, fetchOrganizations } from "@/lib/platform";
import { toast } from "sonner";

export const Route = createFileRoute("/_app/remote-control")({
  component: RemoteControlPage,
  head: () => ({ meta: [{ title: "Remote Control | MugoByte" }] }),
});

function statusVariant(status?: string) {
  const s = (status || "pending").toLowerCase();
  if (s === "completed") return "default" as const;
  if (s === "failed") return "destructive" as const;
  if (s === "running") return "secondary" as const;
  return "outline" as const;
}

function RemoteControlPage() {
  const { orgId, user } = useAuth();
  const qc = useQueryClient();
  const organizationsQ = useQuery({
    queryKey: ["platform-orgs"],
    queryFn: fetchOrganizations,
  });
  const activeOrganization = (organizationsQ.data || []).find(
    (organization) => organization.id === orgId,
  );
  const canOperate = canManageOrganization(activeOrganization, user?.role);

  const [deviceFilter, setDeviceFilter] = useState<string>("");
  const [productId, setProductId] = useState("");
  const [price, setPrice] = useState("");
  const [costPrice, setCostPrice] = useState("");
  const [stockProductId, setStockProductId] = useState("");
  const [stockQty, setStockQty] = useState("");
  const [stockReason, setStockReason] = useState("System Correction");
  const [stockNotes, setStockNotes] = useState("");
  const [username, setUsername] = useState("");
  const [userActive, setUserActive] = useState(false);

  const devicesQ = useQuery({
    queryKey: ["cloud-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
    enabled: Boolean(orgId),
  });
  const commandsQ = useQuery({
    queryKey: ["cloud-commands", orgId, deviceFilter],
    queryFn: () =>
      listCloudCommands({
        orgId,
        deviceId: deviceFilter || undefined,
        limit: 40,
      }),
    enabled: Boolean(orgId),
    refetchInterval: 15_000,
  });

  const devices: CloudDevice[] = devicesQ.data?.devices || [];
  const commands: RemoteCommandRow[] = commandsQ.data?.commands || [];
  const pendingCount = useMemo(
    () => commands.filter((c) => (c.status || "").toLowerCase() === "pending").length,
    [commands],
  );

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["cloud-commands", orgId] });
    devicesQ.refetch();
    commandsQ.refetch();
  };

  const productMut = useMutation({
    mutationFn: () => {
      const fields: Record<string, number> = {};
      if (price.trim() !== "") fields.price = Number(price);
      if (costPrice.trim() !== "") fields.cost_price = Number(costPrice);
      return remoteOpsUpdateProduct({
        product_id: productId.trim(),
        fields,
        device_id: deviceFilter || undefined,
        primary_only: !deviceFilter,
        org_id: orgId,
      });
    },
    onSuccess: (res) => {
      if (res?.error) {
        toast.error(res.error);
        return;
      }
      toast.success(`Product update queued (${res.commands_issued || 0} device(s))`);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message || "Failed to queue product update"),
  });

  const stockMut = useMutation({
    mutationFn: () =>
      remoteOpsAdjustStock({
        product_id: stockProductId.trim(),
        quantity: Number(stockQty),
        reason: stockReason.trim() || "System Correction",
        notes: stockNotes.trim() || undefined,
        device_id: deviceFilter || undefined,
        primary_only: !deviceFilter,
        org_id: orgId,
      }),
    onSuccess: (res) => {
      if (res?.error) {
        toast.error(res.error);
        return;
      }
      toast.success(`Stock adjust queued (${res.commands_issued || 0} device(s))`);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message || "Failed to queue stock adjust"),
  });

  const userMut = useMutation({
    mutationFn: () =>
      remoteOpsSetUserActive({
        username: username.trim(),
        is_active: userActive,
        device_id: deviceFilter || undefined,
        primary_only: !deviceFilter,
        org_id: orgId,
      }),
    onSuccess: (res) => {
      if (res?.error) {
        toast.error(res.error);
        return;
      }
      toast.success(`User ${userActive ? "enable" : "disable"} queued`);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message || "Failed to queue user change"),
  });

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Remote control"
        description="Queue product, stock, and user commands to shop PCs. Applies when the shop PC is online; queued while offline."
        actions={
          <Button variant="outline" onClick={invalidate}>
            <RefreshCw className="mr-1.5 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <Card className="mb-4 border-dashed">
        <CardContent className="flex gap-3 p-4 text-sm text-muted-foreground">
          <Clock className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium text-foreground">
              Applies when shop PC is online; queued while offline
            </p>
            <p className="mt-1">
              Commands poll about every 30 seconds. Shop→cloud sync still pushes local
              changes after the POS applies them. This is not a full remote POS —
              sales, refunds, voids, purchases, and expenses are not included in Phase 1.
            </p>
          </div>
        </CardContent>
      </Card>

      {organizationsQ.isLoading ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Verifying organization permissions…
          </CardContent>
        </Card>
      ) : !canOperate ? (
        <Card>
          <CardContent className="flex gap-3 p-6 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Owner or org admin access is required for remote operations.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <MonitorSmartphone className="h-4 w-4" />
                Devices
              </CardTitle>
              <CardDescription>
                Optional target — empty sends to the primary/active device set.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button
                variant={deviceFilter === "" ? "default" : "outline"}
                size="sm"
                className="w-full justify-start"
                onClick={() => setDeviceFilter("")}
              >
                All active / primary
              </Button>
              {devices.map((d) => {
                const id = d.device_id || d.id || "";
                const online = isCloudDeviceOnline(d);
                return (
                  <Button
                    key={id}
                    variant={deviceFilter === id ? "default" : "outline"}
                    size="sm"
                    className="w-full justify-between"
                    onClick={() => setDeviceFilter(id)}
                  >
                    <span className="truncate">
                      {d.hostname || d.computer_name || id}
                    </span>
                    <Badge variant={online ? "default" : "secondary"}>
                      {online ? "online" : "offline"}
                    </Badge>
                  </Button>
                );
              })}
              {devices.length === 0 && (
                <p className="text-sm text-muted-foreground">No devices registered yet.</p>
              )}
              <p className="pt-2 text-xs text-muted-foreground">
                {pendingCount} pending in recent history
              </p>
            </CardContent>
          </Card>

          <div className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Package className="h-4 w-4" />
                  Update product price / cost
                </CardTitle>
                <CardDescription>
                  Uses local shop product id (source id). Leave a field blank to skip it.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1.5">
                  <Label htmlFor="rc-pid">Product ID</Label>
                  <Input
                    id="rc-pid"
                    value={productId}
                    onChange={(e) => setProductId(e.target.value)}
                    placeholder="e.g. 42"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rc-price">Price</Label>
                  <Input
                    id="rc-price"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    placeholder="optional"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rc-cost">Cost</Label>
                  <Input
                    id="rc-cost"
                    value={costPrice}
                    onChange={(e) => setCostPrice(e.target.value)}
                    placeholder="optional"
                  />
                </div>
                <div className="sm:col-span-3">
                  <Button
                    disabled={
                      productMut.isPending
                      || !productId.trim()
                      || (price.trim() === "" && costPrice.trim() === "")
                    }
                    onClick={() => productMut.mutate()}
                  >
                    Queue product update
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Warehouse className="h-4 w-4" />
                  Adjust stock
                </CardTitle>
                <CardDescription>
                  Signed quantity (positive adds, negative removes). Reason is required.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="rc-spid">Product ID</Label>
                  <Input
                    id="rc-spid"
                    value={stockProductId}
                    onChange={(e) => setStockProductId(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rc-sqty">Quantity (signed)</Label>
                  <Input
                    id="rc-sqty"
                    value={stockQty}
                    onChange={(e) => setStockQty(e.target.value)}
                    placeholder="+5 or -2"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rc-sreason">Reason</Label>
                  <Input
                    id="rc-sreason"
                    value={stockReason}
                    onChange={(e) => setStockReason(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rc-snotes">Notes</Label>
                  <Input
                    id="rc-snotes"
                    value={stockNotes}
                    onChange={(e) => setStockNotes(e.target.value)}
                    placeholder="optional"
                  />
                </div>
                <div className="sm:col-span-2">
                  <Button
                    disabled={
                      stockMut.isPending
                      || !stockProductId.trim()
                      || stockQty.trim() === ""
                      || !stockReason.trim()
                    }
                    onClick={() => stockMut.mutate()}
                  >
                    Queue stock adjust
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <UserCog className="h-4 w-4" />
                  Disable / enable user
                </CardTitle>
                <CardDescription>
                  Prefer disable over PIN reset. Matches local shop username.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="rc-user">Username</Label>
                  <Input
                    id="rc-user"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </div>
                <div className="flex items-end gap-2">
                  <Button
                    variant={userActive ? "default" : "outline"}
                    onClick={() => setUserActive(true)}
                  >
                    Enable
                  </Button>
                  <Button
                    variant={!userActive ? "default" : "outline"}
                    onClick={() => setUserActive(false)}
                  >
                    Disable
                  </Button>
                </div>
                <div className="sm:col-span-2">
                  <Button
                    disabled={userMut.isPending || !username.trim()}
                    onClick={() => userMut.mutate()}
                  >
                    Queue user {userActive ? "enable" : "disable"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="h-4 w-4" />
            Pending / recent commands
          </CardTitle>
          <CardDescription>Status: pending · running · completed · failed</CardDescription>
        </CardHeader>
        <CardContent>
          {commandsQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading commands…</p>
          ) : commandsQ.data?.error && commands.length === 0 ? (
            <p className="text-sm text-destructive">{commandsQ.data.error}</p>
          ) : commands.length === 0 ? (
            <p className="text-sm text-muted-foreground">No commands yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Issued</th>
                    <th className="py-2 pr-3 font-medium">Command</th>
                    <th className="py-2 pr-3 font-medium">Device</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {commands.map((c) => (
                    <tr key={c.id || `${c.command}-${c.issued_at}`} className="border-b last:border-0">
                      <td className="py-2 pr-3 whitespace-nowrap">
                        {c.issued_at ? new Date(c.issued_at).toLocaleString() : "—"}
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">{c.command}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{c.device_id || "—"}</td>
                      <td className="py-2 pr-3">
                        <Badge variant={statusVariant(c.status)}>
                          {(c.status || "pending").toLowerCase()}
                        </Badge>
                      </td>
                      <td className="py-2 text-muted-foreground max-w-[280px] truncate">
                        {c.error || (typeof c.result === "string" ? c.result : "") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
