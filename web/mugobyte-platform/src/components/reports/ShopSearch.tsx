import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes, CreditCard, Receipt, Search, UserRound, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GET } from "@/lib/api";
import { type AnalyticsResponse, type AnalyticsRow, formatMoney, formatDateTime, value } from "./analytics";
import { cn } from "@/lib/utils";

type SearchGroups = {
  sales?: AnalyticsRow[];
  products?: AnalyticsRow[];
  debts?: AnalyticsRow[];
  customers?: AnalyticsRow[];
};

export function ShopSearch({
  orgId,
  onNavigate,
  className,
}: {
  orgId: string;
  onNavigate?: (tab: string, hint?: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 280);
    return () => window.clearTimeout(t);
  }, [q]);

  const query = useQuery({
    queryKey: ["cloud-analytics-search", orgId, debounced],
    queryFn: () =>
      GET<AnalyticsResponse & { groups?: SearchGroups; total?: number }>(
        "/cloud/analytics/search",
        { org_id: orgId, q: debounced },
      ),
    enabled: Boolean(orgId) && debounced.length >= 2 && open,
    retry: false,
  });

  const groups = (query.data?.groups || {}) as SearchGroups;
  const sections = useMemo(
    () =>
      [
        {
          key: "sales",
          label: "Sales",
          icon: Receipt,
          tab: "sales",
          rows: groups.sales || [],
          render: (row: AnalyticsRow) => ({
            title: String(value(row, "receipt_number", "receipt") || "Sale"),
            meta: `${formatDateTime(value(row, "source_created_at", "created_at"))} · ${formatMoney(value(row, "total"), "KES")}`,
          }),
        },
        {
          key: "products",
          label: "Products",
          icon: Boxes,
          tab: "inventory",
          rows: groups.products || [],
          render: (row: AnalyticsRow) => ({
            title: String(value(row, "name") || "Product"),
            meta: `Stock ${value(row, "stock") ?? "—"} · ${formatMoney(value(row, "price"), "KES")}`,
          }),
        },
        {
          key: "debts",
          label: "Debts",
          icon: CreditCard,
          tab: "debts",
          rows: groups.debts || [],
          render: (row: AnalyticsRow) => ({
            title: String(value(row, "customer_name", "name") || "Debtor"),
            meta: `${value(row, "invoice_number") || "Invoice"} · bal ${formatMoney(value(row, "balance"), "KES")}`,
          }),
        },
        {
          key: "customers",
          label: "Customers",
          icon: UserRound,
          tab: "debts",
          rows: groups.customers || [],
          render: (row: AnalyticsRow) => ({
            title: String(value(row, "name", "customer_name") || "Customer"),
            meta: String(value(row, "phone", "email") || ""),
          }),
        },
      ].filter((s) => s.rows.length > 0),
    [groups],
  );

  return (
    <div className={cn("relative w-full max-w-md", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Search sales, stock, debts…"
          className="h-10 rounded-xl border-border/70 bg-background/80 pl-9 pr-9"
          aria-label="Global shop search"
        />
        {q ? (
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:bg-muted"
            onClick={() => {
              setQ("");
              setDebounced("");
            }}
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      {open && debounced.length >= 2 ? (
        <div className="absolute left-0 right-0 z-40 mt-2 max-h-[70vh] overflow-auto rounded-xl border border-border/80 bg-popover p-2 shadow-elegant">
          {query.isLoading ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">Searching…</p>
          ) : sections.length === 0 ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">No matches in this shop.</p>
          ) : (
            sections.map((section) => (
              <div key={section.key} className="mb-2 last:mb-0">
                <p className="flex items-center gap-1.5 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  <section.icon className="h-3.5 w-3.5" />
                  {section.label}
                </p>
                <div className="space-y-0.5">
                  {section.rows.map((row, index) => {
                    const item = section.render(row);
                    return (
                      <Button
                        key={`${section.key}-${String(value(row, "source_id", "id") || index)}`}
                        variant="ghost"
                        className="h-auto w-full justify-start rounded-lg px-3 py-2 text-left"
                        onClick={() => {
                          setOpen(false);
                          onNavigate?.(section.tab, debounced);
                        }}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{item.title}</span>
                          <span className="block truncate text-xs text-muted-foreground">{item.meta}</span>
                        </span>
                      </Button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      ) : null}
      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-30 cursor-default bg-transparent"
          aria-label="Close search"
          onClick={() => setOpen(false)}
        />
      ) : null}
    </div>
  );
}
