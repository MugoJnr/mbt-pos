import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST, getUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApi } from "@/lib/download";

export const Route = createFileRoute("/stocktake")({
  component: StocktakePage,
});

const TABS = ["Active", "Review", "History"] as const;

function StocktakePage() {
  const { user } = useAuth();
  const role = String(user?.role || getUser()?.role || "").toLowerCase();
  const canReview = ["manager", "admin", "superadmin"].includes(role);
  const canAdjust = ["admin", "superadmin"].includes(role);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Active");
  const [selected, setSelected] = useState<number | null>(null);
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["stocktakes"],
    queryFn: () => GET<{ stocktakes: any[]; last_sync: string | null }>("/stocktakes"),
  });
  const detailQ = useQuery({
    queryKey: ["stocktake", selected],
    queryFn: () => GET<any>(`/stocktakes/${selected}`),
    enabled: !!selected,
  });
  const rows = listQ.data?.stocktakes || [];
  const detail = detailQ.data;
  const summary = detail?.summary;

  async function act(path: string, body?: unknown) {
    try {
      await POST(path, body || {});
      toast.success("Saved");
      qc.invalidateQueries({ queryKey: ["stocktakes"] });
      qc.invalidateQueries({ queryKey: ["stocktake", selected] });
    } catch (err: any) {
      toast.error(err?.message || "Could not save");
    }
  }

  return (
    <AppShell title="Stocktake">
      <PageHeader
        eyebrow="Inventory"
        title="Stocktake & Reconciliation"
        icon={<ClipboardCheck className="h-4 w-4" />}
        description="Compare counted stock with movements since the count started. Counting does not change inventory."
      />
      <p className="mb-3 text-sm text-text2">
        Last synced: {listQ.data?.last_sync || "not recorded"}. This page reads the shop database on this computer.
      </p>
      <div className="mb-4 flex gap-2">
        {TABS.map((name) => (
          <Button key={name} size="sm" variant={tab === name ? "primary" : "secondary"} onClick={() => setTab(name)}>
            {name}
          </Button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card className="p-3">
          {rows.filter((row) => {
            if (tab === "History") return ["ADJUSTED", "CANCELLED", "APPROVED"].includes(row.status);
            if (tab === "Review") return ["SUBMITTED", "UNDER_REVIEW", "RECOUNT_REQUIRED"].includes(row.status);
            return ["IN_PROGRESS", "RECOUNT_REQUIRED", "SUBMITTED"].includes(row.status);
          }).map((row) => (
            <button
              key={row.id}
              className="mb-2 block w-full rounded-lg border border-border px-3 py-2 text-left"
              onClick={() => setSelected(row.id)}
            >
              <div className="font-medium">{row.name}</div>
              <div className="text-xs text-text2">
                {row.reference} · {row.status} · {row.counted}/{row.products}
              </div>
            </button>
          ))}
          {!rows.length ? <p className="text-sm text-text2">No stocktakes yet. Start one on the shop till.</p> : null}
        </Card>
        <Card className="p-4">
          {!detail?.stocktake ? <p className="text-sm text-text2">Select a stocktake.</p> : null}
          {detail?.stocktake ? (
            <>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="text-lg font-semibold">{detail.stocktake.name}</div>
                  <div className="text-sm text-text2">
                    {detail.stocktake.reference} · started {detail.stocktake.started_at} by {detail.stocktake.created_by_name}
                  </div>
                </div>
                <Badge>{detail.stocktake.status}</Badge>
              </div>
              {summary ? (
                <p className="mb-3 text-sm">
                  Counted {summary.counted}/{summary.products}. Matched {summary.matched ?? "hidden"}.
                  Shortages {summary.shortages ?? "hidden"}. Excess {summary.excess ?? "hidden"}.
                  Shortage cost {summary.shortage_cost ?? "hidden"}. Excess cost {summary.excess_cost ?? "hidden"}.
                  Net {summary.net_cost ?? "hidden"}.
                </p>
              ) : null}
              <Table head={["Product", "Expected", "Physical", "Variance", "Cost impact", "Status"]}>
                {(detail.lines || []).slice(0, 200).map((line: any) => (
                  <tr key={line.line_id}>
                    <td className="px-4 py-2">{line.product_name}</td>
                    <td className="px-4 py-2">{line.expected_qty ?? "—"}</td>
                    <td className="px-4 py-2">{line.physical_qty ?? "—"}</td>
                    <td className="px-4 py-2">{line.variance_qty ?? "—"}</td>
                    <td className="px-4 py-2">{line.cost_impact ?? "—"}</td>
                    <td className="px-4 py-2">{line.status}</td>
                  </tr>
                ))}
              </Table>
              <div className="mt-3 flex flex-wrap gap-2">
                {canReview ? (
                  <Button size="sm" variant="secondary" onClick={() => act(`/stocktakes/${selected}/recount`)}>
                    Request recount
                  </Button>
                ) : null}
                {canAdjust ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      if (window.confirm("Approve these inventory adjustments?")) {
                        act(`/stocktakes/${selected}/apply`, { reason: "Web approval of physical count" });
                      }
                    }}
                  >
                    Accept and adjust stock
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => act(`/stocktakes/${selected}/request-adjust`, { reason: "Physical count should update stock" })}
                  >
                    Request admin approval
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => downloadApi(`/stocktakes/${selected}/export`, "stocktake.xlsx").catch((err) => toast.error(err.message))}
                >
                  Export
                </Button>
              </div>
            </>
          ) : null}
        </Card>
      </div>
    </AppShell>
  );
}
