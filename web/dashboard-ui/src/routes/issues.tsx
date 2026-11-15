import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState, Input, PageHeader } from "@/components/ui-kit";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/issues")({
  component: IssuesPage,
});

type Issue = {
  id: number;
  rule_code: string;
  severity: "info" | "attention" | "important" | "critical";
  title: string;
  explanation: string;
  status: string;
  first_detected?: string;
  destination?: { web?: string; product_id?: number; sale_id?: number };
  evidence?: { name?: string; price?: number; cost_price?: number };
};

type Payload = {
  issues: Issue[];
  summary: { open: number; info: number; attention: number; important: number; critical: number };
};

const TONE: Record<string, "info" | "warn" | "err" | "ok"> = {
  info: "info",
  attention: "warn",
  important: "err",
  critical: "err",
};

function IssuesPage() {
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const qc = useQueryClient();
  const [status, setStatus] = useState("open");
  const [reason, setReason] = useState("");
  const [cost, setCost] = useState("");
  const q = useQuery({
    queryKey: ["issues", status],
    queryFn: () => GET<Payload>(`/issues?status=${status}&scan=1`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["issues"] });
  const dismiss = useMutation({
    mutationFn: (id: number) => POST(`/issues/${id}/dismiss`, { reason }),
    onSuccess: (res: { error?: string; success?: boolean }) => {
      if (res?.error) toast.error(res.error);
      else {
        toast.success("Dismissed. It stays dismissed until the evidence changes.");
        setReason("");
        refresh();
      }
    },
  });
  const snooze = useMutation({
    mutationFn: (id: number) => POST(`/issues/${id}/snooze`, { days: 3, reason }),
    onSuccess: (res: { error?: string }) => {
      if (res?.error) toast.error(res.error);
      else {
        toast.success("Snoozed for 3 days. It is not resolved.");
        setReason("");
        refresh();
      }
    },
  });
  const saveCost = useMutation({
    mutationFn: (productId: number) => PUT(`/products/${productId}`, { cost_price: Number(cost) }),
    onSuccess: (res: { error?: string; success?: boolean }) => {
      if (res?.error || res?.success === false) toast.error(res?.error || "The price was not saved.");
      else {
        toast.success("Buying price saved. The issue is being checked again.");
        setCost("");
        refresh();
      }
    },
  });

  const rows = q.data?.issues || [];
  const counts = q.data?.summary;
  const canManage = ["manager", "admin", "superadmin"].includes(role);

  return (
    <AppShell title="Issues">
      <PageHeader
        eyebrow="Operations"
        title="Business issues"
        icon={<AlertTriangle className="h-4 w-4" />}
        description="These warnings do not stop a sale. Opening a row does not mark it resolved."
        actions={
          <Button variant="secondary" onClick={refresh} className="min-h-[44px]">
            Check again
          </Button>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(["critical", "important", "attention", "info"] as const).map((level) => (
          <Card key={level} className="p-3">
            <div className="text-xs uppercase tracking-wide text-text2">{level}</div>
            <div className="text-2xl font-semibold tabular-nums">{counts?.[level] ?? "—"}</div>
          </Card>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {["open", "snoozed", "dismissed", "resolved"].map((item) => (
          <Button
            key={item}
            variant={status === item ? "primary" : "secondary"}
            onClick={() => setStatus(item)}
            className="min-h-[40px] capitalize"
          >
            {item}
          </Button>
        ))}
      </div>
      {q.isLoading ? (
        <div className="py-12 text-center text-sm text-text2">Checking the shop records…</div>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<AlertTriangle className="h-8 w-8 text-muted-fg" />}
            title={`No ${status} issues you can see`}
            description="A cashier does not see buying prices, profit, or journal details."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((issue) => {
            const productId = issue.destination?.product_id;
            const href = issue.destination?.web || "/inventory";
            const costRule = ["INV-NO-BUYING-PRICE", "INV-NEGATIVE-COST", "INV-SELL-BELOW-COST"].includes(issue.rule_code);
            return (
              <Card key={issue.id} className="p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone={TONE[issue.severity] || "info"}>{issue.severity}</Badge>
                  <span className="text-xs text-text2">{issue.rule_code}</span>
                  <span className="text-xs text-text2">{(issue.first_detected || "").slice(0, 16)}</span>
                </div>
                <h3 className="font-semibold text-text">{issue.title}</h3>
                <p className="mt-1 text-sm text-text2">{issue.explanation}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <a href={href} className="text-sm font-semibold text-gold underline">
                    Open {productId ? "inventory" : "the related screen"}
                  </a>
                  {costRule && productId && status === "open" ? (
                    <>
                      <Input
                        value={cost}
                        onChange={(event) => setCost(event.target.value)}
                        placeholder="Buying price"
                        className="h-10 w-36"
                      />
                      <Button
                        variant="primary"
                        className="min-h-[40px]"
                        disabled={saveCost.isPending}
                        onClick={() => saveCost.mutate(productId)}
                      >
                        Save buying price
                      </Button>
                    </>
                  ) : null}
                </div>
                {status === "open" && canManage && issue.severity !== "critical" ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Input
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="Reason, if you dismiss or snooze"
                      className="h-10 min-w-[240px] flex-1"
                    />
                    <Button variant="secondary" className="min-h-[40px]" onClick={() => snooze.mutate(issue.id)}>
                      Snooze 3 days
                    </Button>
                    <Button variant="secondary" className="min-h-[40px]" onClick={() => dismiss.mutate(issue.id)}>
                      Dismiss
                    </Button>
                  </div>
                ) : null}
              </Card>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
