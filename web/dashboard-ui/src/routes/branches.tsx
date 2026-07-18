import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitBranch, MapPin, Check } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState, SectionTitle } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/branches")({
  component: BranchesPage,
});

const BRANCH_KEY = "mbt_branch_id";

type Branch = {
  id: number;
  code: string;
  name: string;
  is_current?: number;
  address?: string;
  phone?: string;
  today_revenue?: number | null;
  products?: number | null;
};

function BranchesPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["branches"],
    queryFn: () => GET<{ branches: Branch[] }>("/branches"),
  });
  const selectM = useMutation({
    mutationFn: (id: number) => POST(`/branches/${id}/select`, {}),
    onSuccess: (_data, id) => {
      localStorage.setItem(BRANCH_KEY, String(id));
      qc.invalidateQueries({ queryKey: ["branches"] });
    },
  });

  const branches = q.data?.branches || [];
  const stored = localStorage.getItem(BRANCH_KEY);

  return (
    <AppShell title="Branches">
      <div className="mb-4">
        <h2 className="text-xl font-bold text-text flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-gold" /> Branch Management
        </h2>
        <p className="text-sm text-text2">
          Switch active branch context. Multi-location comparison uses available shop data.
        </p>
      </div>

      {q.isLoading ? (
        <div className="py-12 text-center text-sm text-text2">Loading branches…</div>
      ) : branches.length === 0 ? (
        <Card>
          <EmptyState title="No branches" description="Default branch will be created on first API call." />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {branches.map((b) => {
            const current = Boolean(b.is_current) || stored === String(b.id);
            return (
              <Card key={b.id} className={`p-4 ${current ? "border-gold/50" : ""}`}>
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div>
                    <div className="text-[10px] tracking-[0.16em] uppercase text-text2 font-semibold">
                      {b.code}
                    </div>
                    <div className="text-lg font-bold text-text">{b.name}</div>
                  </div>
                  {current ? <Badge tone="gold">Current</Badge> : null}
                </div>
                {(b.address || b.phone) && (
                  <div className="flex items-start gap-2 text-sm text-text2 mb-3">
                    <MapPin className="h-4 w-4 shrink-0 mt-0.5" />
                    <span>
                      {b.address || "—"}
                      {b.phone ? ` · ${b.phone}` : ""}
                    </span>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
                  <div className="rounded-md bg-panel/50 p-3">
                    <div className="text-[10px] tracking-[0.14em] uppercase text-text2">
                      Today revenue
                    </div>
                    <div className="font-bold text-gold tabular-nums mt-0.5">
                      {b.today_revenue != null ? KES(b.today_revenue) : "—"}
                    </div>
                  </div>
                  <div className="rounded-md bg-panel/50 p-3">
                    <div className="text-[10px] tracking-[0.14em] uppercase text-text2">
                      Products
                    </div>
                    <div className="font-bold text-text mt-0.5">
                      {b.products != null ? b.products : "—"}
                    </div>
                  </div>
                </div>
                {!current ? (
                  <Button
                    variant="primary"
                    className="w-full min-h-[44px]"
                    disabled={selectM.isPending}
                    onClick={() => selectM.mutate(b.id)}
                  >
                    <Check className="h-4 w-4" /> Switch Context
                  </Button>
                ) : (
                  <div className="text-xs text-ok font-semibold text-center py-2">
                    Active context
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      <Card className="p-4 mt-4">
        <SectionTitle>Comparison note</SectionTitle>
        <p className="text-sm text-text2 leading-relaxed">
          This install shares one local database. Additional branch rows are placeholders for
          multi-location deployments; live metrics attach to the current branch only until
          remote branch APIs are linked.
        </p>
      </Card>
    </AppShell>
  );
}
