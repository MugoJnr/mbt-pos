import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, RefreshCw } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/inventory")({
  component: Inventory,
});

type Product = {
  id: number;
  name: string;
  sku?: string;
  category?: string;
  price: number;
  cost_price?: number;
  stock: number;
  min_stock?: number;
  unit?: string;
};

function Inventory() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const currency = settingsQ.data?.currency_symbol || "KES";
  const products = Array.isArray(productsQ.data) ? productsQ.data : [];

  const list = useMemo(
    () =>
      products.filter(
        (p) =>
          q === "" ||
          p.name.toLowerCase().includes(q.toLowerCase()) ||
          (p.sku || "").toLowerCase().includes(q.toLowerCase()),
      ),
    [products, q],
  );

  const totalValue = products.reduce(
    (s, p) => s + Number(p.stock || 0) * Number(p.cost_price ?? p.price ?? 0),
    0,
  );
  const lowCount = products.filter(
    (p) => Number(p.stock) > 0 && Number(p.stock) <= Number(p.min_stock ?? 5),
  ).length;

  return (
    <AppShell title="Inventory">
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
          <Input
            placeholder="Search by name or SKU…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-8"
          />
        </div>
        <Button
          variant="ghost"
          onClick={() => qc.invalidateQueries({ queryKey: ["products"] })}
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      <Card className="overflow-hidden">
        {productsQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading inventory…</div>
        ) : (
          <Table
            head={["Name", "SKU", "Category", "Price", "Cost", "Stock", "Unit"]}
          >
            {list.map((p) => {
              const stock = Number(p.stock) || 0;
              const oos = stock === 0;
              const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
              return (
                <tr key={p.id}>
                  <td className="px-4 py-2.5 text-text font-medium">{p.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-text2">{p.sku || "—"}</td>
                  <td className="px-4 py-2.5 text-text2">{p.category || "General"}</td>
                  <td className="px-4 py-2.5 tabular-nums text-gold font-semibold">
                    {KES(p.price, currency)}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-text2">
                    {KES(p.cost_price ?? 0, currency)}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">
                    <Badge tone={oos ? "err" : low ? "warn" : "muted"}>{stock}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-text2">{p.unit || "pcs"}</td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      <div className="mt-3 flex items-center justify-between text-xs text-text2">
        <div>
          <span className="text-text font-semibold">{products.length}</span> products
          <span className="text-muted-fg mx-2">·</span>
          <span className="text-warn font-semibold">{lowCount}</span> low stock
        </div>
        <div>
          Stock value:{" "}
          <span className="text-gold font-bold text-sm tabular-nums">
            {KES(totalValue, currency)}
          </span>
        </div>
      </div>
    </AppShell>
  );
}
