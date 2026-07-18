import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Trash2,
  CreditCard,
  Banknote,
  Smartphone,
  ShoppingBag,
  Star,
  Clock,
  LayoutGrid,
  List,
  Building2,
  SplitSquareVertical,
  PauseCircle,
  StickyNote,
  ArrowRight,
  UserRound,
  Printer,
  Eye,
  Package,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";
import { cn } from "@/lib/utils";

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
  image_url?: string;
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

const PAGE_SIZE = 9;
const PAY_METHODS = [
  { k: "Cash", i: Banknote, accent: "ok" as const },
  { k: "M-Pesa", i: Smartphone, accent: "ok" as const },
  { k: "Card", i: CreditCard, accent: "info" as const },
  { k: "Bank", i: Building2, accent: "info" as const },
  { k: "Split", i: SplitSquareVertical, accent: "gold" as const },
];
const QUICK_AMOUNTS = [500, 1000, 2000, 5000] as const;

function POS() {
  const qc = useQueryClient();
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<Line[]>([]);
  const [held, setHeld] = useState<Line[] | null>(null);
  const [discount, setDiscount] = useState(0);
  const [payment, setPayment] = useState("Cash");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [showNote, setShowNote] = useState(false);
  const [favorites, setFavorites] = useState<Set<number>>(() => new Set());
  const [favOnly, setFavOnly] = useState(false);
  const [recentOnly, setRecentOnly] = useState(false);
  const [recentIds, setRecentIds] = useState<number[]>([]);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [page, setPage] = useState(1);
  const [customerLabel] = useState("Walk-in Customer");

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

  const filtered = useMemo(() => {
    return products.filter((p) => {
      const matchCat = !cat || (p.category || "General") === cat;
      const qq = q.toLowerCase();
      const matchQ =
        !qq ||
        p.name.toLowerCase().includes(qq) ||
        (p.sku || "").toLowerCase().includes(qq);
      const matchFav = !favOnly || favorites.has(p.id);
      const matchRecent = !recentOnly || recentIds.includes(p.id);
      return matchCat && matchQ && matchFav && matchRecent;
    });
  }, [products, cat, q, favOnly, favorites, recentOnly, recentIds]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageSafe = Math.min(page, pageCount);
  const pageItems = filtered.slice((pageSafe - 1) * PAGE_SIZE, pageSafe * PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [cat, q, favOnly, recentOnly]);

  useEffect(() => {
    const onPosQuery = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      setQ(typeof detail === "string" ? detail : "");
    };
    window.addEventListener("mbt-pos-query", onPosQuery);
    return () => window.removeEventListener("mbt-pos-query", onPosQuery);
  }, []);

  const subtotal = cart.reduce((s, l) => s + l.total, 0);
  const disc = Math.min(discount, subtotal);
  const taxable = Math.max(0, subtotal - disc);
  const tax = Math.round(taxable * taxRate * 100) / 100;
  const total = Math.max(0, taxable + tax);
  const paid = parseFloat(amount) || 0;
  const change = Math.max(0, paid - total);
  const itemCount = cart.reduce((s, l) => s + l.quantity, 0);

  const add = (p: Product) => {
    if (Number(p.stock) <= 0) return;
    setRecentIds((ids) => [p.id, ...ids.filter((id) => id !== p.id)].slice(0, 24));
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

  const setLineDiscount = (product_id: number, d: number) =>
    setCart((c) =>
      c.map((l) => {
        if (l.product_id !== product_id) return l;
        const discountAmt = Math.max(0, Math.min(d, l.unit_price * l.quantity));
        return {
          ...l,
          discount: discountAmt,
          total: Math.round((l.unit_price * l.quantity - discountAmt) * 100) / 100,
        };
      }),
    );

  const toggleFavorite = (id: number, e: MouseEvent) => {
    e.stopPropagation();
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const holdSale = () => {
    if (!cart.length) {
      toast.error("Cart is empty");
      return;
    }
    setHeld(cart);
    setCart([]);
    toast.success("Sale held");
  };

  const restoreHeld = () => {
    if (!held?.length) return;
    setCart(held);
    setHeld(null);
    toast.success("Held sale restored");
  };

  const clearCart = () => {
    setCart([]);
    setDiscount(0);
    setAmount("");
    setNote("");
  };

  const checkout = useMutation({
    mutationFn: async () => {
      if (!cart.length) throw new Error("Add items first");
      const method = payment === "Split" ? "Cash" : payment;
      if (method !== "Credit Sale" && paid < total) {
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
          payment_method: method.toLowerCase(),
          amount_paid: method === "Credit Sale" ? 0 : paid,
          change_amount: Math.max(0, paid - total),
          note: note || undefined,
        },
      );
      if (!res?.success) throw new Error(res?.error || "Sale failed");
      return res;
    },
    onSuccess: (res) => {
      toast.success(`Sale recorded — ${res.receipt_number}`);
      clearCart();
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["sales-today"] });
      qc.invalidateQueries({ queryKey: ["reports-summary"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F12") {
        e.preventDefault();
        if (!checkout.isPending && cart.length) checkout.mutate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cart.length, checkout]);

  const catPills = categories.filter(Boolean);
  const visibleCats = catPills.slice(0, 5);
  const moreCats = catPills.slice(5);

  return (
    <AppShell title="Point of Sale" density="pos">
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_minmax(300px,340px)_minmax(300px,360px)] gap-3 min-h-[calc(100vh-7.5rem)]">
        {/* ── Products ─────────────────────────────────────────── */}
        <Card className="flex flex-col overflow-hidden min-h-[420px]">
          <div className="p-3 border-b border-border flex flex-col gap-2.5 bg-panel/30">
            <div className="flex items-center gap-2 flex-wrap">
              <Select
                value={cat}
                onChange={(e) => setCat(e.target.value)}
                className="min-h-[36px] h-9 w-[9.5rem] text-xs"
              >
                <option value="">All Categories</option>
                {catPills.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
              <div className="flex gap-1.5 overflow-x-auto scrollbar-thin flex-1 min-w-0">
                <CatPill active={!cat} onClick={() => setCat("")}>
                  All
                </CatPill>
                {visibleCats.map((c) => (
                  <CatPill key={c} active={cat === c} onClick={() => setCat(c)}>
                    {c}
                  </CatPill>
                ))}
                {moreCats.length > 0 ? (
                  <Select
                    value={moreCats.includes(cat) ? cat : ""}
                    onChange={(e) => setCat(e.target.value)}
                    className="h-9 min-h-0 w-[7.5rem] text-xs rounded-full"
                  >
                    <option value="">More</option>
                    {moreCats.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                ) : null}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <ToolToggle
                  active={favOnly}
                  onClick={() => {
                    setFavOnly((v) => !v);
                    setRecentOnly(false);
                  }}
                  title="Favorites"
                >
                  <Star className={cn("h-3.5 w-3.5", favOnly && "fill-current")} />
                </ToolToggle>
                <ToolToggle
                  active={recentOnly}
                  onClick={() => {
                    setRecentOnly((v) => !v);
                    setFavOnly(false);
                  }}
                  title="Recent"
                >
                  <Clock className="h-3.5 w-3.5" />
                </ToolToggle>
                <div className="flex rounded-lg border border-border overflow-hidden ml-0.5">
                  <ToolToggle
                    active={viewMode === "grid"}
                    onClick={() => setViewMode("grid")}
                    className="rounded-none border-0"
                    title="Grid"
                  >
                    <LayoutGrid className="h-3.5 w-3.5" />
                  </ToolToggle>
                  <ToolToggle
                    active={viewMode === "list"}
                    onClick={() => setViewMode("list")}
                    className="rounded-none border-0 border-l border-border"
                    title="List"
                  >
                    <List className="h-3.5 w-3.5" />
                  </ToolToggle>
                </div>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin p-3">
            {productsQ.isLoading ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {Array.from({ length: 9 }).map((_, i) => (
                  <Skeleton key={i} className="h-[168px] rounded-xl" />
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<ShoppingBag className="h-6 w-6" />}
                title="No products found"
                description="Try another search or category."
              />
            ) : viewMode === "grid" ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {pageItems.map((p) => (
                  <ProductCard
                    key={p.id}
                    p={p}
                    currency={currency}
                    favored={favorites.has(p.id)}
                    onFav={toggleFavorite}
                    onAdd={() => add(p)}
                  />
                ))}
              </div>
            ) : (
              <div className="space-y-1.5">
                {pageItems.map((p) => {
                  const stock = Number(p.stock) || 0;
                  const oos = stock <= 0;
                  const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
                  return (
                    <button
                      key={p.id}
                      disabled={oos}
                      onClick={() => add(p)}
                      className={cn(
                        "w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-ui",
                        oos
                          ? "border-border/50 bg-panel/40 opacity-60 cursor-not-allowed"
                          : "border-border bg-card2 hover:border-gold/60",
                      )}
                    >
                      <Thumb name={p.name} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold text-text truncate">{p.name}</div>
                        <div className="text-[11px] text-text2 font-mono">{p.sku || `#${p.id}`}</div>
                      </div>
                      <StockBadge stock={stock} oos={oos} low={low} unit={p.unit} />
                      <div className="text-sm font-extrabold text-ok tabular-nums">
                        {KES(p.price, currency)}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {filtered.length > PAGE_SIZE ? (
            <div className="border-t border-border px-3 py-2.5 flex items-center justify-between gap-2 bg-panel/20">
              <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
                {Array.from({ length: Math.min(pageCount, 8) }).map((_, i) => {
                  const n = i + 1;
                  return (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setPage(n)}
                      className={cn(
                        "h-8 min-w-8 px-2 rounded-md text-xs font-semibold border transition-ui",
                        pageSafe === n
                          ? "border-info bg-info/15 text-info"
                          : "border-border bg-card2 text-text2 hover:text-text",
                      )}
                    >
                      {n}
                    </button>
                  );
                })}
                {pageCount > 8 ? (
                  <span className="text-xs text-muted-fg px-1">… {pageCount}</span>
                ) : null}
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="shrink-0 border-info/40 text-info hover:bg-info/10"
                disabled={pageSafe >= pageCount}
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              >
                Load More
              </Button>
            </div>
          ) : null}
        </Card>

        {/* ── Current Sale (cart) ──────────────────────────────── */}
        <Card className="flex flex-col overflow-hidden min-h-[360px] xl:max-h-[calc(100vh-7.5rem)]">
          <div className="p-3 border-b border-border flex items-center justify-between gap-2 bg-panel/30">
            <div>
              <h2 className="text-[14px] font-semibold text-text">Current Sale</h2>
              <div className="text-[11px] text-text2">Selected Items ({itemCount})</div>
            </div>
            <div className="flex items-center gap-1.5">
              {held?.length ? (
                <button
                  type="button"
                  onClick={restoreHeld}
                  className="h-8 px-2 rounded-lg border border-info/40 text-[11px] font-semibold text-info hover:bg-info/10 transition-ui"
                >
                  Resume
                </button>
              ) : null}
              <button
                type="button"
                onClick={holdSale}
                className="h-8 px-2.5 rounded-lg border border-warn/45 text-[11px] font-semibold text-warn hover:bg-warn/10 inline-flex items-center gap-1 transition-ui"
              >
                <PauseCircle className="h-3.5 w-3.5" /> Hold Sale
              </button>
              <button
                type="button"
                onClick={clearCart}
                className="h-8 px-2.5 rounded-lg border border-err/45 text-[11px] font-semibold text-err hover:bg-err/10 transition-ui"
              >
                Clear Cart
              </button>
            </div>
          </div>

          <div className="px-3 py-1.5 border-b border-border/60 grid grid-cols-[1fr_52px_64px_52px_64px_28px] gap-1 text-[10px] uppercase tracking-wide text-muted-fg font-semibold">
            <span>Item</span>
            <span className="text-center">Qty</span>
            <span className="text-right">Price</span>
            <span className="text-right">Disc</span>
            <span className="text-right">Total</span>
            <span />
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin min-h-[100px]">
            {cart.length === 0 ? (
              <EmptyState
                icon={<ShoppingBag className="h-6 w-6" />}
                title="Cart is empty"
                description="Tap a product to add it."
                className="py-12"
              />
            ) : (
              cart.map((l) => (
                <div
                  key={l.product_id}
                  className="grid grid-cols-[1fr_52px_64px_52px_64px_28px] gap-1 items-center px-3 py-2.5 border-b border-border/40"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Thumb name={l.product_name} small />
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium text-text truncate leading-tight">
                        {l.product_name}
                      </div>
                      <div className="text-[10px] text-text2 font-mono truncate">
                        {l.sku || `#${l.product_id}`}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center justify-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => setQty(l.product_id, l.quantity - 1)}
                      className="h-7 w-7 rounded-md border border-border bg-input text-text text-sm hover:bg-hover transition-ui"
                      aria-label="Decrease"
                    >
                      −
                    </button>
                    <span className="w-5 text-center text-[12px] font-bold text-text tabular-nums">
                      {l.quantity}
                    </span>
                    <button
                      type="button"
                      onClick={() => setQty(l.product_id, l.quantity + 1)}
                      className="h-7 w-7 rounded-md border border-border bg-input text-text text-sm hover:bg-hover transition-ui"
                      aria-label="Increase"
                    >
                      +
                    </button>
                  </div>
                  <div className="text-[11px] text-right tabular-nums text-text2">
                    {KES(l.unit_price, currency)}
                  </div>
                  <input
                    type="number"
                    value={l.discount || ""}
                    onChange={(e) => setLineDiscount(l.product_id, parseFloat(e.target.value) || 0)}
                    className="h-7 w-full rounded-md border border-border bg-input px-1 text-[11px] text-right text-text tabular-nums"
                    placeholder="0"
                  />
                  <div className="text-[12px] font-semibold text-right tabular-nums text-text">
                    {KES(l.total, currency)}
                  </div>
                  <button
                    type="button"
                    onClick={() => setQty(l.product_id, 0)}
                    className="h-7 w-7 inline-flex items-center justify-center rounded-md text-text2 hover:text-err hover:bg-err/10 transition-ui"
                    aria-label="Remove"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="border-t border-border px-3 py-2.5">
            {showNote ? (
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Sale note…"
                className="h-9 text-sm mb-1"
                autoFocus
              />
            ) : null}
            <button
              type="button"
              onClick={() => setShowNote((v) => !v)}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-info hover:text-info/80 transition-ui"
            >
              <StickyNote className="h-3.5 w-3.5" />
              {showNote ? "Hide note" : "+ Add Note to Sale"}
            </button>
          </div>
        </Card>

        {/* ── Checkout ─────────────────────────────────────────── */}
        <Card className="flex flex-col overflow-hidden min-h-[360px] xl:max-h-[calc(100vh-7.5rem)]">
          <div className="p-3 border-b border-border flex items-center justify-between gap-2 bg-panel/30">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="h-9 w-9 rounded-full bg-info/20 text-info grid place-items-center shrink-0">
                <UserRound className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] text-muted-fg uppercase tracking-wide">Customer</div>
                <div className="text-sm font-semibold text-text truncate">{customerLabel}</div>
              </div>
            </div>
            <button
              type="button"
              className="h-8 px-2.5 rounded-lg border border-border text-[11px] font-semibold text-text2 hover:text-text hover:bg-hover transition-ui"
              onClick={() => toast.message("Customer picker — coming in a follow-up")}
            >
              Change
            </button>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-fg mb-2">
                Order Summary
              </div>
              <div className="space-y-2">
                <Row label="Subtotal" value={KES(subtotal, currency)} />
                <div className="flex items-center justify-between text-sm gap-3">
                  <span className="text-text2 shrink-0">Discount</span>
                  <Input
                    type="number"
                    value={discount || ""}
                    onChange={(e) => setDiscount(parseFloat(e.target.value) || 0)}
                    className="h-9 w-28 text-right"
                    placeholder="0"
                  />
                </div>
                {disc > 0 ? (
                  <Row label="Discount applied" value={`− ${KES(disc, currency)}`} tone="ok" />
                ) : null}
                <Row
                  label={`Tax (${(taxRate * 100).toFixed(0)}%)`}
                  value={KES(tax, currency)}
                />
                <div className="flex items-center justify-between pt-2 border-t border-border">
                  <span className="text-sm font-semibold text-text tracking-wide">Total</span>
                  <span className="text-[1.65rem] font-extrabold text-gold tabular-nums tracking-tight leading-none">
                    {KES(total, currency)}
                  </span>
                </div>
              </div>
            </div>

            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-fg mb-2">
                Payment Method
              </div>
              <div className="grid grid-cols-5 gap-1.5">
                {PAY_METHODS.map((m) => {
                  const Icon = m.i;
                  const active = payment === m.k;
                  return (
                    <button
                      key={m.k}
                      type="button"
                      onClick={() => setPayment(m.k)}
                      className={cn(
                        "min-h-[56px] rounded-xl border text-[10px] font-semibold flex flex-col items-center justify-center gap-1 transition-ui px-0.5",
                        active
                          ? m.accent === "ok"
                            ? "border-ok bg-ok/12 text-ok shadow-[0_0_0_1px_color-mix(in_oklab,var(--ok)_35%,transparent)]"
                            : m.accent === "info"
                              ? "border-info bg-info/12 text-info"
                              : "border-gold bg-gold/15 text-gold shadow-gold"
                          : "border-border bg-card2 text-text2 hover:text-text hover:border-border2",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="leading-tight text-center">{m.k === "Split" ? "Split" : m.k}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-fg">
                Amount Tendered
              </div>
              <Input
                type="number"
                placeholder="0.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="min-h-[44px] h-11 text-[16px] font-semibold tabular-nums"
              />
              <div className="grid grid-cols-5 gap-1.5">
                {QUICK_AMOUNTS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setAmount(String(n))}
                    className={cn(
                      "h-9 rounded-lg border text-[11px] font-semibold transition-ui",
                      amount === String(n)
                        ? "border-gold bg-gold/15 text-gold"
                        : "border-border bg-card2 text-text2 hover:text-text",
                    )}
                  >
                    {n}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setAmount(total > 0 ? String(total.toFixed(2)) : "")}
                  className="h-9 rounded-lg border border-border bg-card2 text-[11px] font-semibold text-text2 hover:text-text transition-ui"
                >
                  Exact
                </button>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-ok/25 bg-ok/8 px-3 py-2.5">
                <span className="text-sm text-text2">Change</span>
                <span className="text-lg font-extrabold text-ok tabular-nums">
                  {KES(change, currency)}
                </span>
              </div>
            </div>
          </div>

          <div className="border-t border-border p-3 space-y-2 bg-panel/30">
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => toast.message("Receipt preview — use desktop POS for full print")}
                className="min-h-[40px] rounded-xl border border-border bg-card2 text-[11px] font-semibold text-text2 hover:text-text inline-flex items-center justify-center gap-1.5 transition-ui"
              >
                <Eye className="h-3.5 w-3.5" /> Preview (F9)
              </button>
              <button
                type="button"
                onClick={() => toast.message("Reprint — use desktop POS for hardware printer")}
                className="min-h-[40px] rounded-xl border border-border bg-card2 text-[11px] font-semibold text-text2 hover:text-text inline-flex items-center justify-center gap-1.5 transition-ui"
              >
                <Printer className="h-3.5 w-3.5" /> Reprint (F10)
              </button>
            </div>
            <Button
              variant="primary"
              size="touch"
              className="w-full text-[15px] !bg-ok hover:!bg-ok/90 !text-[#04150e] border-ok shadow-[0_4px_18px_-4px_color-mix(in_oklab,var(--ok)_50%,transparent)]"
              disabled={checkout.isPending || cart.length === 0}
              onClick={() => checkout.mutate()}
            >
              {checkout.isPending ? (
                "Processing…"
              ) : (
                <span className="inline-flex items-center gap-2">
                  Complete Sale (F12)
                  <ArrowRight className="h-4 w-4" />
                </span>
              )}
            </Button>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function CatPill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "shrink-0 min-h-[34px] px-3 rounded-full text-xs font-semibold border transition-ui",
        active
          ? "border-info bg-info/15 text-info"
          : "border-border bg-card2 text-text2 hover:text-text",
      )}
    >
      {children}
    </button>
  );
}

function ToolToggle({
  active,
  onClick,
  children,
  title,
  className,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cn(
        "h-9 w-9 inline-flex items-center justify-center rounded-lg border transition-ui",
        active
          ? "border-gold bg-gold/15 text-gold"
          : "border-border bg-card2 text-text2 hover:text-text",
        className,
      )}
    >
      {children}
    </button>
  );
}

function Thumb({ name, small }: { name: string; small?: boolean }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
  return (
    <div
      className={cn(
        "shrink-0 rounded-lg bg-panel border border-border grid place-items-center text-muted-fg",
        small ? "h-8 w-8" : "h-10 w-10",
      )}
    >
      {small ? (
        <span className="text-[9px] font-bold">{initials || "?"}</span>
      ) : (
        <Package className="h-4 w-4 opacity-70" />
      )}
    </div>
  );
}

function StockBadge({
  stock,
  oos,
  low,
  unit,
}: {
  stock: number;
  oos: boolean;
  low: boolean;
  unit?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold",
        oos ? "bg-err/15 text-err" : low ? "bg-warn/15 text-warn" : "bg-ok/12 text-ok",
      )}
    >
      {oos ? "Out of Stock" : low ? `Low · ${stock}` : `${stock} ${unit || "pcs"}`}
    </span>
  );
}

function ProductCard({
  p,
  currency,
  favored,
  onFav,
  onAdd,
}: {
  p: Product;
  currency: string;
  favored: boolean;
  onFav: (id: number, e: MouseEvent) => void;
  onAdd: () => void;
}) {
  const stock = Number(p.stock) || 0;
  const oos = stock <= 0;
  const low = stock > 0 && stock <= Number(p.min_stock ?? 5);
  const priceTone = low || oos ? "text-warn" : "text-ok";

  return (
    <button
      type="button"
      disabled={oos}
      onClick={onAdd}
      className={cn(
        "relative text-left rounded-xl border overflow-hidden transition-ui group",
        oos
          ? "border-border/50 bg-panel/40 opacity-65 cursor-not-allowed"
          : "border-border bg-card2 hover:border-gold/55 hover:shadow-md active:scale-[0.98]",
      )}
    >
      <div className="relative h-[88px] bg-gradient-to-br from-panel via-[#121c30] to-card2 border-b border-border/50 grid place-items-center">
        {p.image_url ? (
          <img src={p.image_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <Package className="h-8 w-8 text-muted-fg/70" />
        )}
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => onFav(p.id, e)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onFav(p.id, e as unknown as MouseEvent);
          }}
          className="absolute top-2 right-2 h-7 w-7 rounded-full bg-app/70 border border-border grid place-items-center text-text2 hover:text-gold transition-ui"
          aria-label="Favorite"
        >
          <Star className={cn("h-3.5 w-3.5", favored && "fill-gold text-gold")} />
        </span>
      </div>
      <div className="p-2.5">
        <div className="text-[13px] font-semibold text-text leading-tight line-clamp-2 min-h-[2.35em]">
          {p.name}
        </div>
        <div className="mt-1 text-[10px] text-text2 font-mono truncate">{p.sku || `#${p.id}`}</div>
        <div className="mt-2 flex items-end justify-between gap-1">
          <StockBadge stock={stock} oos={oos} low={low} unit={p.unit} />
          <div className={cn("text-[14px] font-extrabold tabular-nums", priceTone)}>
            {KES(p.price, currency)}
          </div>
        </div>
      </div>
    </button>
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
