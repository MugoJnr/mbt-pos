import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Trash2, CreditCard, Banknote, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, Select } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/pos")({
  component: POS,
});

type Product = {
  id: number;
  name: string;
  sku?: string;
  category?: string;
  price: number;
  stock: number;
  min_stock?: number;
  unit?: string;
};

type Line = {
  product_id: number;
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
};

function POS() {
  const qc = useQueryClient();
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<Line[]>([]);
  const [discount, setDiscount] = useState(0);
  const [payment, setPayment] = useState("Cash");
  const [amount, setAmount] = useState("");

  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });

  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const currency = settingsQ.data?.currency_symbol || "KES";
  const taxRate = (parseFloat(settingsQ.data?.tax_rate || "0") || 0) / 100;

  const categories = useMemo(() => {
    const set = new Set(products.map((p) => p.category || "General").filter(Boolean));
    return ["", ...Array.from(set).sort()];
  }, [products]);

  const filtered = useMemo(
    () =>
      products.filter((p) => {
        const matchCat = !cat || (p.category || "General") === cat;
        const qq = q.toLowerCase();
        const matchQ =
          !qq ||
          p.name.toLowerCase().includes(qq) ||
          (p.sku || "").toLowerCase().includes(qq);
        return matchCat && matchQ;
      }),
    [products, cat, q],
  );

  const subtotal = cart.reduce((s, l) => s + l.total, 0);
  const disc = Math.min(discount, subtotal);
  const taxable = Math.max(0, subtotal - disc);
  const tax = Math.round(taxable * taxRate * 100) / 100;
  const total = Math.max(0, taxable + tax);
  const paid = parseFloat(amount) || 0;
  const change = Math.max(0, paid - total);

  const add = (p: Product) => {
    if (Number(p.stock) <= 0) return;
    setCart((c) => {
      const ex = c.find((l) => l.product_id === p.id);
      if (ex) {
        const quantity = ex.quantity + 1;
        if (quantity > Number(p.stock)) {
          toast.error(`Only ${p.stock} in stock`);
          return c;
        }
        return c.map((l) =>
          l.product_id === p.id
            ? { ...l, quantity, total: Math.round(quantity * l.unit_price * 100) / 100 }
            : l,
        );
      }
      return [
        ...c,
        {
          product_id: p.id,
          product_name: p.name,
          sku: p.sku || "",
          quantity: 1,
          unit_price: Number(p.price) || 0,
          discount: 0,
          total: Number(p.price) || 0,
        },
      ];
    });
  };

  const setQty = (product_id: number, quantity: number) =>
    setCart((c) =>
      quantity <= 0
        ? c.filter((l) => l.product_id !== product_id)
        : c.map((l) =>
            l.product_id === product_id
              ? {
                  ...l,
                  quantity,
                  total: Math.round(quantity * l.unit_price * 100) / 100,
                }
              : l,
          ),
    );

  const checkout = useMutation({
    mutationFn: async () => {
      if (!cart.length) throw new Error("Add items first");
      if (payment !== "Credit Sale" && paid < total) {
        throw new Error("Amount paid is less than total");
      }
      const res = await POST<{ success?: boolean; error?: string; receipt_number?: string }>(
        "/sales",
        {
          items: cart,
          subtotal,
          discount: disc,
          tax,
          total,
          payment_method: payment.toLowerCase(),
          amount_paid: payment === "Credit Sale" ? 0 : paid,
          change_amount: Math.max(0, paid - total),
        },
      );
      if (!res?.success) throw new Error(res?.error || "Sale failed");
      return res;
    },
    onSuccess: (res) => {
      toast.success(`Sale recorded — ${res.receipt_number}`);
      setCart([]);
      setDiscount(0);
      setAmount("");
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["sales-today"] });
      qc.invalidateQueries({ queryKey: ["reports-summary"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell title="Point of Sale">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_420px] gap-4 h-[calc(100vh-9rem)]">
        <Card className="flex flex-col overflow-hidden">
          <div className="p-3 border-b border-border flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
              <Input
                placeholder="Search products…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-8"
              />
            </div>
            <Select value={cat} onChange={(e) => setCat(e.target.value)}>
              <option value="">All Categories</option>
              {categories.filter(Boolean).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin p-3">
            {productsQ.isLoading ? (
              <div className="py-16 text-center text-sm text-text2">Loading products…</div>
            ) : filtered.length === 0 ? (
              <div className="py-16 text-center text-sm text-text2">No products found</div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2.5">
                {filtered.map((p) => {
                  const stock = Number(p.stock) || 0;
                  const oos = stock <= 0;
                  const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
                  return (
                    <button
                      key={p.id}
                      disabled={oos}
                      onClick={() => add(p)}
                      className={`text-left rounded-lg border p-3 transition-all ${
                        oos
                          ? "border-border/50 bg-panel/40 opacity-60 cursor-not-allowed"
                          : "border-border bg-card2 hover:border-gold/60 active:scale-[0.98]"
                      }`}
                    >
                      <div className="text-[13px] font-semibold text-text leading-tight line-clamp-2 min-h-[2.4em]">
                        {p.name}
                      </div>
                      <div className="mt-2 flex items-center justify-between">
                        <div className="text-[15px] font-extrabold text-gold tabular-nums">
                          {KES(p.price, currency)}
                        </div>
                        <div
                          className={`text-[10px] font-semibold uppercase tracking-wider ${
                            oos ? "text-err" : low ? "text-warn" : "text-text2"
                          }`}
                        >
                          {oos ? "Out" : `${stock} ${p.unit || "pcs"}`}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Card>

        <Card className="flex flex-col overflow-hidden">
          <div className="p-4 border-b border-border flex items-center justify-between">
            <h2 className="text-[15px] font-semibold text-text">Current Sale</h2>
            <span className="text-xs text-text2">
              {cart.reduce((s, l) => s + l.quantity, 0)} items
            </span>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {cart.length === 0 ? (
              <div className="py-16 text-center text-sm text-text2">
                No items yet. Tap a product to add.
              </div>
            ) : (
              cart.map((l) => (
                <div
                  key={l.product_id}
                  className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-2 px-4 py-2.5 border-b border-border/50"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-text truncate">{l.product_name}</div>
                    <div className="text-[11px] text-text2 font-mono">{l.sku || `#${l.product_id}`}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setQty(l.product_id, l.quantity - 1)}
                      className="h-6 w-6 rounded border border-border bg-input text-text hover:bg-hover"
                    >
                      −
                    </button>
                    <span className="w-6 text-center text-sm font-semibold text-text">{l.quantity}</span>
                    <button
                      onClick={() => setQty(l.product_id, l.quantity + 1)}
                      className="h-6 w-6 rounded border border-border bg-input text-text hover:bg-hover"
                    >
                      +
                    </button>
                  </div>
                  <div className="text-xs text-text2 tabular-nums text-right">
                    {KES(l.unit_price, currency)}
                  </div>
                  <div className="text-sm font-semibold text-text tabular-nums text-right w-16">
                    {KES(l.total, currency)}
                  </div>
                  <button
                    onClick={() => setQty(l.product_id, 0)}
                    className="text-text2 hover:text-err"
                    aria-label="Remove"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="border-t border-border p-4 space-y-2 bg-panel/30">
            <Row label="Subtotal" value={KES(subtotal, currency)} />
            <div className="flex items-center justify-between text-sm">
              <span className="text-text2">Discount</span>
              <Input
                type="number"
                value={discount || ""}
                onChange={(e) => setDiscount(parseFloat(e.target.value) || 0)}
                className="h-8 w-28 text-right"
                placeholder="0"
              />
            </div>
            <Row
              label={`Tax (${(taxRate * 100).toFixed(1)}%)`}
              value={KES(tax, currency)}
            />
            <div className="flex items-center justify-between pt-2 border-t border-border">
              <span className="text-sm font-semibold text-text">TOTAL</span>
              <span className="text-2xl font-extrabold text-gold tabular-nums">
                {KES(total, currency)}
              </span>
            </div>

            <div className="pt-3 grid grid-cols-3 gap-2">
              {[
                { k: "Cash", i: <Banknote className="h-4 w-4" /> },
                { k: "M-Pesa", i: <Smartphone className="h-4 w-4" /> },
                { k: "Card", i: <CreditCard className="h-4 w-4" /> },
              ].map((m) => (
                <button
                  key={m.k}
                  onClick={() => setPayment(m.k)}
                  className={`h-10 rounded-md border text-xs font-semibold flex items-center justify-center gap-1.5 ${
                    payment === m.k
                      ? "border-gold bg-gold/15 text-gold"
                      : "border-border bg-card2 text-text2 hover:text-text"
                  }`}
                >
                  {m.i}
                  {m.k}
                </button>
              ))}
            </div>

            <Input
              type="number"
              placeholder="Amount tendered"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <Row label="Change" value={KES(change, currency)} tone="ok" />

            <Button
              variant="primary"
              size="lg"
              className="w-full mt-2"
              disabled={checkout.isPending || cart.length === 0}
              onClick={() => checkout.mutate()}
            >
              {checkout.isPending ? "Processing…" : `Checkout · ${KES(total, currency)}`}
            </Button>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "ok" }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-text2">{label}</span>
      <span className={`tabular-nums font-semibold ${tone === "ok" ? "text-ok" : "text-text"}`}>
        {value}
      </span>
    </div>
  );
}
