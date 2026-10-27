import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
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
  Printer,
  Eye,
  Package,
  Gift,
  Minus,
  Plus,
  Wallet,
  Receipt,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { ProductPhoto, productPhotoSrc } from "@/components/product-photo";
import { Button, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { KES, saleDayCaption, shopTodayISO } from "@/lib/format";
import { wheelStep } from "@/lib/wheel-steps";
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
  image_path?: string;
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
const QTY_STEP = 0.25;

function snapQty(value: number) {
  const n = Math.round(Number(value) * 100) / 100;
  if (!Number.isFinite(n) || n <= 0) return 0;
  return n;
}

function formatQty(value: number) {
  const n = Math.round(value * 100) / 100;
  if (Math.abs(n - Math.round(n)) < 0.001) return String(Math.round(n));
  return n.toFixed(2).replace(/0$/, "");
}
const PAY_METHODS = [
  { k: "Cash", i: Banknote, accent: "ok" as const, enabled: true },
  { k: "M-Pesa", i: Smartphone, accent: "ok" as const, enabled: true },
  { k: "Card", i: CreditCard, accent: "info" as const, enabled: true },
  { k: "Bank", i: Building2, accent: "info" as const, enabled: true },
  { k: "Split", i: SplitSquareVertical, accent: "gold" as const, enabled: true },
  { k: "Credit", i: Wallet, accent: "gold" as const, enabled: true },
  { k: "Part Pay", i: Receipt, accent: "gold" as const, enabled: true },
  { k: "Gift Card", i: Gift, accent: "muted" as const, enabled: false },
];
const QUICK_AMOUNTS = [500, 1000, 2000, 5000] as const;

function POS() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || "");
  const canDate = ["admin", "superadmin", "manager"].includes(role);
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<Line[]>([]);
  const [held, setHeld] = useState<Line[] | null>(null);
  const [discount, setDiscount] = useState(0);
  const [payment, setPayment] = useState("Cash");
  const [amount, setAmount] = useState("");
  const [splitMethod, setSplitMethod] = useState("M-Pesa");
  const [splitAmount, setSplitAmount] = useState("");
  const [qtyDraft, setQtyDraft] = useState<Record<number, string>>({});
  const [cartWide, setCartWide] = useState(false);
  const [note, setNote] = useState("");
  const [saleDate, setSaleDate] = useState(shopTodayISO);
  const [showNote, setShowNote] = useState(false);
  const [favorites, setFavorites] = useState<Set<number>>(() => new Set());
  const [favOnly, setFavOnly] = useState(false);
  const [recentOnly, setRecentOnly] = useState(false);
  const [recentIds, setRecentIds] = useState<number[]>([]);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [page, setPage] = useState(1);
  const [customerId, setCustomerId] = useState<number | "">("");
  const searchRef = useRef<HTMLInputElement>(null);
  const saleDateRef = useRef<HTMLInputElement>(null);
  const saleTokenRef = useRef("");

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
  const qtyStep = wheelStep(settingsQ.data, "wheel_pos_qty");
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
  const splitTyped = splitAmount.trim() === "" ? null : parseFloat(splitAmount) || 0;
  const splitOther = payment === "Split"
    ? (splitTyped == null ? Math.max(0, Math.round((total - paid) * 100) / 100) : splitTyped)
    : 0;
  const tendered = payment === "Split" ? Math.round((paid + splitOther) * 100) / 100 : paid;
  const change = Math.max(0, (payment === "Split" ? tendered : paid) - total);
  const itemCount = cart.reduce((s, l) => s + l.quantity, 0);
  const showTender = payment === "Cash" || payment === "Split" || payment === "M-Pesa" || payment === "Part Pay";

  const add = (p: Product) => {
    if (Number(p.stock) <= 0) return;
    setRecentIds((ids) => [p.id, ...ids.filter((id) => id !== p.id)].slice(0, 24));
    setCart((c) => {
      const ex = c.find((l) => l.product_id === p.id);
      if (ex) {
        const quantity = snapQty(ex.quantity + qtyStep);
        if (quantity > Number(p.stock) + 0.0001) {
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

  const setQty = (product_id: number, quantity: number, stock?: number) => {
    const next = quantity <= 0 ? 0 : snapQty(quantity);
    if (stock != null && next > Number(stock) + 0.0001) {
      toast.error(`Only ${stock} in stock`);
      return;
    }
    setCart((c) =>
      next <= 0
        ? c.filter((l) => l.product_id !== product_id)
        : c.map((l) =>
            l.product_id === product_id
              ? {
                  ...l,
                  quantity: next,
                  total: Math.round((next * l.unit_price - (l.discount || 0)) * 100) / 100,
                }
              : l,
          ),
    );
  };

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
    setSplitAmount("");
    setNote("");
    setCustomerId("");
  };

  const checkout = useMutation({
    mutationFn: async () => {
      if (!cart.length) throw new Error("Add items first");
      if (payment === "Gift Card") throw new Error("Gift Card is not available yet");
      const method =
        payment === "Split" ? "Mixed"
        : payment === "Bank" ? "Bank Transfer"
        : payment === "Credit" ? "Credit Sale"
        : payment === "Part Pay" ? "Part Payment"
        : payment;
      if (payment === "Split" && (paid <= 0 || splitOther <= 0)) {
        throw new Error("Enter both the cash amount and the second payment");
      }
      if (payment === "Split" && tendered + 0.009 < total) {
        throw new Error("Split payments do not cover the total");
      }
      if ((payment === "Credit" || payment === "Part Pay") && !customerId) {
        throw new Error("Choose a customer before a credit or part payment");
      }
      if (payment === "Part Pay" && (!(paid > 0) || paid >= total)) {
        throw new Error("Part payment must be more than zero and less than the total");
      }
      if (method !== "Credit Sale" && method !== "Part Payment" && method !== "Mixed" && paid < total && showTender) {
        throw new Error("Amount paid is less than total");
      }
      const tender = method === "Credit Sale" ? 0 : method === "Part Payment" ? paid : method === "Mixed" ? tendered : (paid || total);
      const res = await POST<{ success?: boolean; error?: string; receipt_number?: string; sale_id?: number }>(
        "/sales",
        {
          items: cart,
          subtotal,
          discount: disc,
          tax,
          total,
          payment_method: method.toLowerCase() === "mixed" ? "Mixed" : method.toLowerCase(),
          amount_paid: tender,
          change_amount: method === "Credit Sale" || method === "Part Payment" ? 0 : Math.max(0, tender - total),
          cash_paid: method === "Mixed" ? paid : method === "Cash" ? tender : 0,
          electronic_paid: method === "Mixed" ? splitOther : 0,
          electronic_method: method === "Mixed" ? (splitMethod === "Bank" ? "Bank Transfer" : splitMethod) : undefined,
          payment_tenders: method === "Mixed" ? [
            { method: splitMethod === "Bank" ? "Bank Transfer" : splitMethod, amount: splitOther },
            { method: "Cash", amount: paid },
          ] : undefined,
          note: note || undefined,
          customer_id: customerId || undefined,
          sale_date: canDate ? saleDate : undefined,
          client_token: saleTokenRef.current || (saleTokenRef.current = crypto.randomUUID()),
        },
      );
      if (!res?.success) throw new Error(res?.error || "Sale failed");
      return res;
    },
    onSuccess: (res) => {
      toast.success(`Sale recorded — ${res.receipt_number}`);
      saleTokenRef.current = "";
      clearCart();
      searchRef.current?.focus();
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

  if (role === "viewer") {
    return (
      <AppShell title="Point of Sale">
        <div className="p-6 text-sm text-text2">You cannot take a payment.</div>
      </AppShell>
    );
  }

  return (
    <AppShell title="Point of Sale" density="pos">
      <div className="flex h-full min-h-0 flex-col gap-2 md:flex-row">
        {/* Products. The cart stays in this same viewport on a phone and on a desktop. */}
        <Card className="flex min-h-0 min-w-0 max-h-[50%] flex-1 basis-0 flex-col overflow-hidden md:max-h-none">
          <div className="p-2 border-b border-border flex flex-col gap-1.5 bg-panel/30">
            <div className="flex items-center gap-1.5">
              <Input
                ref={searchRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search name, SKU, or barcode"
                aria-label="Search products"
                title="A barcode scanner types into this box"
                autoFocus
                className="h-9 min-h-0 text-sm flex-1"
              />
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
            <div className="flex gap-1.5 overflow-x-auto scrollbar-thin">
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
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin p-2">
            {productsQ.isLoading ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <Skeleton key={i} className="h-[92px] rounded-xl" />
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <EmptyState
                icon={<ShoppingBag className="h-6 w-6" />}
                title="No products found"
                description="Try another search or category."
              />
            ) : viewMode === "grid" ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
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
                      <Thumb name={p.name} image={p.image_path || p.image_url} />
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
        <Card className={cartWide
          ? "flex min-h-[240px] w-full flex-1 flex-col overflow-hidden md:h-full md:min-h-0 md:w-[min(760px,68%)] md:min-w-[420px] md:flex-none"
          : "flex min-h-[240px] w-full flex-1 flex-col overflow-hidden md:h-full md:min-h-0 md:w-[min(420px,42%)] md:min-w-[300px] md:flex-none"}>
          <div className="p-3 border-b border-border flex items-center justify-between gap-2 bg-panel/30">
            <div>
              <h2 className="text-[15px] font-semibold text-text">{cartWide ? "View Cart" : "Current Sale"}</h2>
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
                onClick={() => setCartWide((open) => !open)}
                className="min-h-11 px-3 rounded-xl border border-gold/50 text-[12px] font-semibold text-gold hover:bg-gold/10"
              >
                {cartWide ? "Back to products" : "View Cart"}
              </button>
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

          <div className="min-h-[72px] flex-1 overflow-y-auto scrollbar-thin">
            {cart.length === 0 ? (
              <EmptyState
                icon={<ShoppingBag className="h-5 w-5" />}
                title="Cart is empty"
                description="Tap a product to add it."
                className="py-6"
              />
            ) : (
              <div className="divide-y divide-border">
                {cart.map((l) => (
                  <div key={l.product_id} className="px-2 py-1.5 flex items-center gap-1.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-text truncate">{l.product_name}</div>
                      <div className="text-[10px] text-muted-fg font-mono truncate">
                        {l.sku || `#${l.product_id}`} · {KES(l.unit_price, currency)}
                      </div>
                    </div>
                    <div className="inline-flex items-center rounded-lg border border-border bg-input shrink-0">
                      <button
                        type="button"
                        aria-label="Decrease"
                        onClick={() => setQty(l.product_id, l.quantity - qtyStep)}
                        className="h-8 w-8 grid place-items-center text-text hover:bg-hover"
                      >
                        <Minus className="h-3.5 w-3.5" />
                      </button>
                      <input
                        type="number"
                        min={0.01}
                        step={qtyStep}
                        onWheel={(e) => {
                          if (document.activeElement !== e.currentTarget) return;
                          e.preventDefault();
                          const dir = e.deltaY < 0 ? 1 : -1;
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(l.product_id, l.quantity + dir * qtyStep, stock);
                        }}
                        aria-label={`Quantity for ${l.product_name}`}
                        value={qtyDraft[l.product_id] ?? formatQty(l.quantity)}
                        onChange={(e) => {
                          const raw = e.target.value;
                          setQtyDraft((draft) => ({ ...draft, [l.product_id]: raw }));
                          const n = parseFloat(raw);
                          if (!Number.isFinite(n)) return;
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(l.product_id, n, stock);
                        }}
                        onBlur={(e) => {
                          const raw = e.currentTarget.value;
                          setQtyDraft((draft) => {
                            const next = { ...draft };
                            delete next[l.product_id];
                            return next;
                          });
                          if (raw == null || raw.trim() === "") return;
                          const n = parseFloat(raw);
                          if (!Number.isFinite(n)) return;
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(l.product_id, n, stock);
                        }}
                        className="h-8 w-14 border-0 bg-transparent text-center text-[13px] font-bold tabular-nums text-text"
                      />
                      <button
                        type="button"
                        aria-label="Increase"
                        onClick={() =>
                          setQty(
                            l.product_id,
                            l.quantity + qtyStep,
                            products.find((p) => p.id === l.product_id)?.stock,
                          )
                        }
                        className="h-8 w-8 grid place-items-center text-text hover:bg-hover"
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <input
                      type="number"
                      min={0}
                      step={10}
                      value={l.discount || ""}
                      onChange={(e) => setLineDiscount(l.product_id, parseFloat(e.target.value) || 0)}
                      className="h-8 w-14 rounded-lg border border-border bg-input px-1 text-[12px] font-bold text-right text-text tabular-nums shrink-0"
                      placeholder="Disc"
                      title={`Line discount (${currency})`}
                      aria-label={`Line discount in ${currency}`}
                    />
                    <div className="w-16 text-right text-[13px] font-extrabold tabular-nums text-text shrink-0">
                      {KES(l.total, currency)}
                    </div>
                    <button
                      type="button"
                      aria-label="Remove"
                      onClick={() => setQty(l.product_id, 0)}
                      className="h-8 w-8 grid place-items-center rounded-lg text-err hover:bg-err/10 shrink-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="min-h-0 shrink space-y-1.5 overflow-y-auto border-t border-border bg-panel/40 px-2 py-1.5 scrollbar-thin">
            <div className="flex items-center gap-1.5">
              <Select
                value={customerId === "" ? "" : String(customerId)}
                onChange={(e) => setCustomerId(e.target.value ? Number(e.target.value) : "")}
                className="h-8 min-h-0 text-xs flex-1"
                aria-label="Customer"
              >
                <option value="">Walk-in Customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || `Customer #${c.id}`}
                    {c.phone ? ` · ${c.phone}` : ""}
                  </option>
                ))}
              </Select>
              {canDate ? (
                <>
                  <button
                    type="button"
                    aria-label="Sale date"
                    title="Change the sale date. A date other than today is saved as that business day."
                    onClick={() => saleDateRef.current?.showPicker?.()}
                    className={cn(
                      "h-8 rounded-lg border px-2 text-xs font-extrabold",
                      saleDayCaption(saleDate).tone === "today"
                        ? "border-border text-text"
                        : "border-err bg-err/10 text-err",
                    )}
                  >
                    {saleDayCaption(saleDate).text}
                  </button>
                  <input
                    ref={saleDateRef}
                    type="date"
                    tabIndex={-1}
                    aria-hidden
                    value={saleDate}
                    max={shopTodayISO()}
                    onChange={(e) => setSaleDate(e.target.value || shopTodayISO())}
                    className="sr-only"
                  />
                </>
              ) : (
                <span className="text-xs font-extrabold text-text">Today</span>
              )}
            </div>

            <div className="flex items-end justify-between gap-2">
              <div className="min-w-0 text-[11px] leading-tight text-text2">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span>Subtotal {KES(subtotal, currency)}</span>
                  <label className="inline-flex items-center gap-1">
                    Discount
                    <input
                      type="number"
                      value={discount || ""}
                      onChange={(e) => setDiscount(parseFloat(e.target.value) || 0)}
                      className="h-7 w-16 rounded-md border border-border bg-input px-1 text-right text-xs font-bold text-text"
                      placeholder="0"
                      aria-label="Cart discount"
                    />
                  </label>
                  <span>
                    Tax {(taxRate * 100).toFixed(0)}% {KES(tax, currency)}
                  </span>
                </div>
                {disc > 0 ? (
                  <div className="text-ok font-bold">You save {KES(disc, currency)}</div>
                ) : null}
              </div>
              <div className="text-right shrink-0">
                <div className="text-[10px] font-bold uppercase tracking-wide text-muted-fg">Total</div>
                <div className="text-[1.35rem] font-extrabold text-gold tabular-nums leading-none">
                  {KES(total, currency)}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-4 gap-1">
              {PAY_METHODS.map((m) => {
                const Icon = m.i;
                const active = payment === m.k;
                return (
                  <button
                    key={m.k}
                    type="button"
                    disabled={!m.enabled}
                    title={m.enabled ? m.k : "Gift cards are not available. This button does not take payment."}
                    onClick={() => m.enabled && setPayment(m.k)}
                    className={cn(
                      "h-8 rounded-lg border text-[10px] font-bold inline-flex items-center justify-center gap-1 px-1 transition-ui",
                      !m.enabled && "border-dashed border-border text-muted-fg opacity-60 cursor-not-allowed",
                      m.enabled && active && "border-gold bg-gold/15 text-gold",
                      m.enabled && !active && "border-border bg-card2 text-text2 hover:text-text",
                    )}
                  >
                    <Icon className="h-3 w-3 shrink-0" />
                    <span className="truncate">{m.k === "Gift Card" ? "No gift card" : m.k}</span>
                  </button>
                );
              })}
            </div>

            {payment === "Split" ? (
              <div className="space-y-1">
                <div className="flex items-center gap-1">
                  <Input
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder="Cash amount"
                    aria-label="Cash amount"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="h-8 min-h-0 text-sm font-semibold tabular-nums flex-1"
                  />
                  <select
                    aria-label="Second payment"
                    value={splitMethod}
                    onChange={(e) => setSplitMethod(e.target.value)}
                    className="h-8 rounded-lg border border-border bg-input px-2 text-xs font-semibold text-text"
                  >
                    <option>M-Pesa</option>
                    <option>Card</option>
                    <option>Bank</option>
                  </select>
                  <Input
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder={splitOther > 0 ? `Remainder ${splitOther.toFixed(2)}` : "Second amount"}
                    aria-label="Second payment amount"
                    value={splitAmount}
                    onChange={(e) => setSplitAmount(e.target.value)}
                    className="h-8 min-h-0 text-sm font-semibold tabular-nums w-28"
                  />
                </div>
                <div className="text-[11px] font-semibold text-text2">
                  Cash {KES(paid, currency)} + {splitMethod === "Bank" ? "Bank Transfer" : splitMethod}{" "}
                  {KES(splitOther, currency)}
                  {change > 0 ? ` · Change ${KES(change, currency)}` : ""}
                </div>
              </div>
            ) : showTender ? (
              <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
                <Input
                  type="number"
                  placeholder={payment === "M-Pesa" ? "M-Pesa received" : "Amount received"}
                  aria-label={payment === "M-Pesa" ? "Amount received" : "Amount tendered"}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="h-8 min-h-0 text-sm font-semibold tabular-nums flex-1"
                />
                {QUICK_AMOUNTS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setAmount(String(n))}
                    className={cn(
                      "h-8 px-1.5 rounded-lg border text-[10px] font-bold shrink-0",
                      amount === String(n)
                        ? "border-gold bg-gold/15 text-gold"
                        : "border-border bg-card2 text-text2",
                    )}
                  >
                    {n >= 1000 ? `${n / 1000}k` : n}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setAmount(total > 0 ? String(total.toFixed(2)) : "")}
                  className="h-8 px-2 rounded-lg border border-border bg-card2 text-[10px] font-bold text-text2 shrink-0"
                >
                  Exact
                </button>
                <span className="text-[11px] font-extrabold text-ok tabular-nums whitespace-nowrap pl-1">
                  Change {KES(change, currency)}
                </span>
              </div>
            ) : (
              <div className="text-[11px] text-text2 px-0.5">
                {payment === "Card" || payment === "Bank"
                  ? "No cash tender for this method."
                  : payment === "Credit"
                    ? "Full amount stays on the customer account."
                    : "Choose a customer, then enter the amount paid now."}
              </div>
            )}

            {showNote ? (
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Sale note"
                aria-label="Sale note"
                className="h-8 min-h-0 text-sm"
                autoFocus
              />
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1 border-t border-border bg-panel px-2 py-1.5">
              <button
                type="button"
                title={showNote ? "Hide note" : "Add note"}
                onClick={() => setShowNote((v) => !v)}
                className="h-10 w-10 shrink-0 rounded-lg border border-border bg-card2 text-gold grid place-items-center"
              >
                <StickyNote className="h-4 w-4" />
              </button>
              <button
                type="button"
                title="Receipt preview"
                onClick={() => toast.message("Receipt preview — use desktop POS for full print")}
                className="h-10 w-10 shrink-0 rounded-lg border border-border bg-card2 text-text2 grid place-items-center"
              >
                <Eye className="h-4 w-4" />
              </button>
              <button
                type="button"
                title="Reprint"
                onClick={() => toast.message("Reprint — use desktop POS for hardware printer")}
                className="h-10 w-10 shrink-0 rounded-lg border border-border bg-card2 text-text2 grid place-items-center"
              >
                <Printer className="h-4 w-4" />
              </button>
              <Button
                variant="primary"
                className="h-10 min-h-0 flex-1 text-[14px] !bg-ok hover:!bg-ok/90 !text-[#04150e] border-ok"
                disabled={checkout.isPending || cart.length === 0}
                onClick={() => checkout.mutate()}
              >
                {checkout.isPending ? (
                  "Processing…"
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    Complete Sale
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

function Thumb({ name, image, small }: { name: string; image?: string; small?: boolean }) {
  const src = productPhotoSrc(image);
  if (src) {
    return <img src={src} alt="" title={name} className={cn("shrink-0 rounded-xl object-cover", small ? "h-8 w-8" : "h-12 w-12")} />;
  }
  return <ProductPhoto size={small ? "sm" : "md"} />;
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
      <div className="relative h-16 bg-gradient-to-br from-panel via-[#121c30] to-card2 border-b border-border/50 grid place-items-center overflow-hidden">
        {productPhotoSrc(p.image_path || p.image_url) ? (
          <img src={productPhotoSrc(p.image_path || p.image_url)} alt="" className="h-full w-full object-cover" />
        ) : (
          <ProductPhoto size="sm" />
        )}
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => onFav(p.id, e)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onFav(p.id, e as unknown as MouseEvent);
          }}
          className="absolute top-1 right-1 h-5 w-5 rounded-full bg-app/70 border border-border grid place-items-center text-text2 hover:text-gold transition-ui"
          aria-label="Favorite"
        >
          <Star className={cn("h-3 w-3", favored && "fill-gold text-gold")} />
        </span>
      </div>
      <div className="px-2 py-1.5">
        <div className="text-[12px] font-semibold text-text leading-tight truncate">
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
