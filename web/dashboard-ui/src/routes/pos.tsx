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
  Gift,
  Minus,
  Plus,
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

type Customer = {
  id: number;
  name?: string;
  phone?: string;
  customer_type?: string;
  type?: string;
  wallet_balance?: number;
  loyalty_points?: number;
  outstanding_balance?: number;
  balance?: number;
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

const PAGE_SIZE = 12;
const PAY_METHODS = [
  { k: "Cash", i: Banknote, accent: "ok" as const, enabled: true },
  { k: "M-Pesa", i: Smartphone, accent: "ok" as const, enabled: true },
  { k: "Card", i: CreditCard, accent: "info" as const, enabled: true },
  { k: "Bank", i: Building2, accent: "info" as const, enabled: true },
  { k: "Split", i: SplitSquareVertical, accent: "gold" as const, enabled: true },
  /** Future-ready stub — not backed by checkout API yet */
  { k: "Gift Card", i: Gift, accent: "muted" as const, enabled: false },
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
  const [customerId, setCustomerId] = useState<number | "">("");

  const productsQ = useQuery({
    queryKey: ["products"],
    queryFn: () => GET<Product[]>("/products"),
  });
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const customersQ = useQuery({
    queryKey: ["customers"],
    queryFn: () => GET<Customer[]>("/customers"),
  });

  const products = Array.isArray(productsQ.data) ? productsQ.data : [];
  const customers = Array.isArray(customersQ.data) ? customersQ.data : [];
  const currency = settingsQ.data?.currency_symbol || "KES";
  const taxRate = (parseFloat(settingsQ.data?.tax_rate || "0") || 0) / 100;

  const selectedCustomer = useMemo(
    () => (customerId === "" ? null : customers.find((c) => c.id === customerId) || null),
    [customers, customerId],
  );

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

  const subtotal = cart.reduce((s, l) => s + l.unit_price * l.quantity, 0);
  const lineDisc = cart.reduce((s, l) => s + (l.discount || 0), 0);
  const disc = Math.min(discount + lineDisc, subtotal);
  const taxable = Math.max(0, subtotal - disc);
  const tax = Math.round(taxable * taxRate * 100) / 100;
  const total = Math.max(0, taxable + tax);
  const paid = parseFloat(amount) || 0;
  const change = Math.max(0, paid - total);
  const itemCount = cart.reduce((s, l) => s + l.quantity, 0);
  const showTender = payment === "Cash" || payment === "Split" || payment === "M-Pesa";

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
            ? {
                ...l,
                quantity,
                total: Math.round((quantity * l.unit_price - (l.discount || 0)) * 100) / 100,
              }
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
                  total: Math.round((quantity * l.unit_price - (l.discount || 0)) * 100) / 100,
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
      if (payment === "Gift Card") throw new Error("Gift Card is not available yet");
      const method =
        payment === "Split" ? "Cash" : payment === "Bank" ? "Bank Transfer" : payment;
      if (method !== "Credit Sale" && paid < total && showTender) {
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
          amount_paid: method === "Credit Sale" ? 0 : paid || total,
          change_amount: Math.max(0, (paid || total) - total),
          note: note || undefined,
          customer_id: customerId || undefined,
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
  const wallet = Number(selectedCustomer?.wallet_balance || 0);
  const outstanding = Number(
    selectedCustomer?.outstanding_balance ?? selectedCustomer?.balance ?? 0,
  );
  const loyalty = selectedCustomer?.loyalty_points;

  return (
    <AppShell title="Point of Sale" density="pos">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.35fr)_minmax(380px,0.95fr)] gap-3 min-h-[calc(100vh-7.5rem)]">
        {/* ── LEFT: Products ───────────────────────────────────── */}
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
                  title="Recently sold"
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
                          ? "border-gold bg-gold/15 text-gold"
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
                className="shrink-0"
                disabled={pageSafe >= pageCount}
                onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              >
                Load More
              </Button>
            </div>
          ) : null}
        </Card>

        {/* ── RIGHT: Cart + Customer + Summary + Payment ───────── */}
        <Card className="flex flex-col overflow-hidden min-h-[360px] xl:max-h-[calc(100vh-7.5rem)]">
          <div className="p-3 border-b border-border flex items-center justify-between gap-2 bg-panel/30">
            <div>
              <h2 className="text-[15px] font-semibold text-text">Current Sale</h2>
              <div className="text-[11px] text-text2">
                {itemCount} item{itemCount === 1 ? "" : "s"} in cart
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              {held?.length ? (
                <button
                  type="button"
                  onClick={restoreHeld}
                  className="min-h-11 px-3 rounded-xl border border-info/40 text-[12px] font-semibold text-info hover:bg-info/10 transition-ui"
                >
                  Resume
                </button>
              ) : null}
              <button
                type="button"
                onClick={holdSale}
                className="min-h-11 px-3 rounded-xl border border-warn/45 text-[12px] font-semibold text-warn hover:bg-warn/10 inline-flex items-center gap-1.5 transition-ui"
              >
                <PauseCircle className="h-4 w-4" /> Hold
              </button>
              <button
                type="button"
                onClick={clearCart}
                className="min-h-11 px-3 rounded-xl border border-err/45 text-[12px] font-semibold text-err hover:bg-err/10 transition-ui"
              >
                Clear
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin min-h-0">
            <div className="p-3 space-y-2.5 border-b border-border/60">
              {cart.length === 0 ? (
                <EmptyState
                  icon={<ShoppingBag className="h-6 w-6" />}
                  title="Cart is empty"
                  description="Tap a product to add it."
                  className="py-10"
                />
              ) : (
                cart.map((l) => (
                  <div
                    key={l.product_id}
                    className="rounded-xl border border-border bg-card2/80 hover:border-gold/40 px-3 py-3 transition-ui"
                  >
                    <div className="flex gap-3">
                      <Thumb name={l.product_name} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[13px] font-semibold text-text leading-snug line-clamp-2">
                          {l.product_name}
                        </div>
                        <div className="text-[11px] text-muted-fg font-mono mt-0.5">
                          {l.sku || `#${l.product_id}`}
                        </div>
                        <div className="text-[12px] text-text2 mt-1 tabular-nums">
                          {KES(l.unit_price, currency)} each
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-[15px] font-extrabold text-text tabular-nums">
                          {KES(l.total, currency)}
                        </div>
                        <button
                          type="button"
                          onClick={() => setQty(l.product_id, 0)}
                          className="mt-2 ml-auto h-11 w-11 inline-flex items-center justify-center rounded-xl text-err hover:bg-err/10 transition-ui"
                          aria-label="Remove"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <div className="inline-flex items-center gap-2 rounded-xl border border-border bg-input px-2 py-1.5 min-h-11">
                        <span className="text-[11px] font-extrabold uppercase tracking-wide text-muted-fg shrink-0 pl-1">
                          Qty
                        </span>
                        <button
                          type="button"
                          onClick={() => setQty(l.product_id, l.quantity - 1)}
                          className="h-11 w-11 grid place-items-center rounded-lg text-text hover:bg-hover active:scale-95 transition-ui"
                          aria-label="Decrease"
                        >
                          <Minus className="h-4 w-4" />
                        </button>
                        <span className="min-w-[2.25rem] text-center text-[14px] font-bold tabular-nums text-text">
                          {l.quantity}
                        </span>
                        <button
                          type="button"
                          onClick={() => setQty(l.product_id, l.quantity + 1)}
                          className="h-11 w-11 grid place-items-center rounded-lg text-text hover:bg-hover active:scale-95 transition-ui"
                          aria-label="Increase"
                        >
                          <Plus className="h-4 w-4" />
                        </button>
                      </div>
                      <label className="inline-flex items-center gap-2 rounded-xl border border-gold/50 bg-gold/10 px-3 min-h-11">
                        <span className="text-[11px] font-extrabold text-gold shrink-0 whitespace-nowrap">
                          Discount ({currency})
                        </span>
                        <input
                          type="number"
                          min={0}
                          step={10}
                          value={l.discount || ""}
                          onChange={(e) =>
                            setLineDiscount(l.product_id, parseFloat(e.target.value) || 0)
                          }
                          className="h-11 flex-1 min-w-0 rounded-lg border border-border bg-input px-2 text-[14px] font-bold text-right text-text tabular-nums"
                          placeholder="0.00"
                          aria-label={`Line discount in ${currency}`}
                        />
                      </label>
                      {(l.discount || 0) > 0.009 ? (
                        <div className="sm:col-span-2 text-[11px] font-extrabold text-ok">
                          Save {KES(l.discount || 0, currency)} on this item
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="p-3 border-b border-border/60">
              <div className="rounded-xl border border-border bg-card2/70 p-3">
                <div className="flex items-start gap-3">
                  <div className="h-11 w-11 rounded-full bg-gold/15 text-gold grid place-items-center shrink-0 border border-gold/30">
                    <UserRound className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] text-muted-fg uppercase tracking-wide font-bold">
                      Customer
                    </div>
                    <div className="text-sm font-bold text-text truncate">
                      {selectedCustomer?.name || "Walk-in Customer"}
                    </div>
                    <div className="text-[12px] text-text2 truncate mt-0.5">
                      {selectedCustomer
                        ? [
                            selectedCustomer.phone,
                            selectedCustomer.customer_type || selectedCustomer.type,
                          ]
                            .filter(Boolean)
                            .join(" · ") || "No phone on file"
                        : "Cash customer · no account"}
                    </div>
                    {selectedCustomer &&
                    (wallet > 0.009 || outstanding > 0.009 || loyalty != null) ? (
                      <div className="text-[11px] text-ok font-semibold mt-1 truncate">
                        {[
                          loyalty != null && loyalty !== "" ? `Loyalty ${loyalty}` : null,
                          wallet > 0.009 ? `Credit ${KES(wallet, currency)}` : null,
                          outstanding > 0.009 ? `Due ${KES(outstanding, currency)}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    ) : null}
                  </div>
                </div>
                <Select
                  value={customerId === "" ? "" : String(customerId)}
                  onChange={(e) =>
                    setCustomerId(e.target.value ? Number(e.target.value) : "")
                  }
                  className="mt-3 min-h-11 h-11 text-sm"
                >
                  <option value="">Walk-in Customer</option>
                  {customers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name || `Customer #${c.id}`}
                      {c.phone ? ` · ${c.phone}` : ""}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="p-3 space-y-4">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-muted-fg mb-2">
                  Order Summary
                </div>
                <div className="space-y-2">
                  <Row label="Subtotal" value={KES(subtotal, currency)} />
                  <div className="flex items-center justify-between text-sm gap-3">
                    <span className="text-text2 shrink-0">Cart discount</span>
                    <Input
                      type="number"
                      value={discount || ""}
                      onChange={(e) => setDiscount(parseFloat(e.target.value) || 0)}
                      className="h-11 w-28 text-right"
                      placeholder="0"
                    />
                  </div>
                  {disc > 0 ? (
                    <Row label="You save" value={`− ${KES(disc, currency)}`} tone="ok" />
                  ) : null}
                  <Row
                    label={`Tax (${(taxRate * 100).toFixed(0)}%)`}
                    value={KES(tax, currency)}
                  />
                  <div className="flex items-center justify-between pt-2 border-t border-border">
                    <span className="text-[15px] font-bold text-text">Grand Total</span>
                    <span
                      key={total}
                      className="text-[1.85rem] font-extrabold text-gold tabular-nums tracking-tight leading-none transition-transform duration-200"
                    >
                      {KES(total, currency)}
                    </span>
                  </div>
                </div>
              </div>

              <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-muted-fg mb-2">
                  Payment Method
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {PAY_METHODS.map((m) => {
                    const Icon = m.i;
                    const active = payment === m.k;
                    return (
                      <button
                        key={m.k}
                        type="button"
                        disabled={!m.enabled}
                        title={
                          m.enabled
                            ? m.k
                            : "Gift Card / Store Credit — coming soon (future-ready stub)"
                        }
                        onClick={() => m.enabled && setPayment(m.k)}
                        className={cn(
                          "min-h-[56px] rounded-xl border text-[11px] font-semibold flex flex-col items-center justify-center gap-1 transition-ui px-1",
                          !m.enabled &&
                            "border-dashed border-border2 bg-panel/40 text-muted-fg cursor-not-allowed opacity-70",
                          m.enabled &&
                            active &&
                            m.accent === "ok" &&
                            "border-ok bg-ok/12 text-ok",
                          m.enabled &&
                            active &&
                            m.accent === "info" &&
                            "border-info bg-info/12 text-info",
                          m.enabled &&
                            active &&
                            m.accent === "gold" &&
                            "border-gold bg-gold/15 text-gold shadow-gold",
                          m.enabled &&
                            !active &&
                            "border-border bg-card2 text-text2 hover:text-text hover:border-gold/40",
                        )}
                      >
                        <Icon className="h-4 w-4" />
                        <span className="leading-tight text-center">
                          {m.k === "Gift Card" ? "Gift*" : m.k}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {showTender ? (
                <div className="space-y-2">
                  <div className="text-[11px] font-bold uppercase tracking-wide text-muted-fg">
                    {payment === "M-Pesa" ? "Amount Received" : "Amount Tendered"}
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
                          "h-11 rounded-xl border text-[11px] font-semibold transition-ui",
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
                      className="h-11 rounded-xl border border-border bg-card2 text-[11px] font-semibold text-text2 hover:text-text transition-ui"
                    >
                      Exact
                    </button>
                  </div>
                  <div className="flex items-center justify-between rounded-xl border border-ok/25 bg-ok/8 px-4 py-3">
                    <span className="text-sm font-semibold text-text2">Change Due</span>
                    <span className="text-2xl font-extrabold text-ok tabular-nums">
                      {KES(change, currency)}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-border bg-panel/40 px-4 py-3 text-[12px] text-text2">
                  {payment === "Card" || payment === "Bank"
                    ? "No cash tender needed for this method."
                    : "Select Cash, M-Pesa, or Split to enter tender."}
                </div>
              )}

              <div>
                {showNote ? (
                  <Input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Sale note…"
                    className="h-11 text-sm mb-2"
                    autoFocus
                  />
                ) : null}
                <button
                  type="button"
                  onClick={() => setShowNote((v) => !v)}
                  className="inline-flex items-center gap-1.5 text-[12px] font-medium text-gold hover:text-gold/80 transition-ui"
                >
                  <StickyNote className="h-3.5 w-3.5" />
                  {showNote ? "Hide note" : "+ Add Note to Sale"}
                </button>
              </div>
            </div>
          </div>

          <div className="border-t border-border p-3 space-y-2 bg-panel/30">
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => toast.message("Receipt preview — use desktop POS for full print")}
                className="min-h-[44px] rounded-xl border border-border bg-card2 text-[12px] font-semibold text-text2 hover:text-text inline-flex items-center justify-center gap-1.5 transition-ui"
              >
                <Eye className="h-4 w-4" /> Preview
              </button>
              <button
                type="button"
                onClick={() => toast.message("Reprint — use desktop POS for hardware printer")}
                className="min-h-[44px] rounded-xl border border-border bg-card2 text-[12px] font-semibold text-text2 hover:text-text inline-flex items-center justify-center gap-1.5 transition-ui"
              >
                <Printer className="h-4 w-4" /> Reprint
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
          ? "border-gold bg-gold/15 text-gold"
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
        "shrink-0 rounded-xl bg-panel border border-border grid place-items-center text-muted-fg",
        small ? "h-8 w-8" : "h-12 w-12",
      )}
    >
      {small ? (
        <span className="text-[9px] font-bold">{initials || "?"}</span>
      ) : (
        <span className="text-[11px] font-bold text-gold/90">{initials || "?"}</span>
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
