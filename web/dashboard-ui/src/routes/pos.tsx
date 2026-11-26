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
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { ProductPhoto, productPhotoSrc } from "@/components/product-photo";
import { Button, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui-kit";
import { CopySaleDialog, type CopiedLine } from "@/components/copy-sale-dialog";
import { SaleDocumentPanel } from "@/components/sale-document-panel";
import { GET, POST } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BackdateReasonPicker, backdateWarning, normalizeBackdateReason } from "@/components/business-date-field";
import { KES, saleDayCaption, shopTodayISO } from "@/lib/format";
import { parseQuantity, quantityStep } from "@/lib/quantity";
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
  allow_decimal_qty?: number | null;
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
  line_id?: string;
  product_id: number;
  product_name: string;
  sku: string;
  unit?: string;
  allow_decimal_qty?: number | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  batch_priced?: boolean;
  fifo_override?: boolean;
  layer_id?: number;
  override_reason?: string;
};

function lineKey(line: Line) {
  return line.line_id || `p${line.product_id}`;
}

function lineTotal(price: number, quantity: number, discount: number) {
  return Math.round((price * quantity - Math.max(0, discount)) * 100) / 100;
}

const HELD_KEY = "mbt-pos-held-sale";
function saleQtyStep(unit: string | undefined, wheel: number, decimalQty?: unknown) {
  return quantityStep(unit, wheel, decimalQty);
}

function readHeldSale(): Line[] | null {
  try {
    const raw = localStorage.getItem(HELD_KEY);
    const data = raw ? JSON.parse(raw) : null;
    return Array.isArray(data) && data.length ? data : null;
  } catch {
    return null;
  }
}

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
  { k: "Airtel Money", i: Smartphone, accent: "ok" as const, enabled: true },
  { k: "Cheque", i: Receipt, accent: "info" as const, enabled: true },
  { k: "Split", i: SplitSquareVertical, accent: "gold" as const, enabled: true },
  { k: "Credit", i: Wallet, accent: "gold" as const, enabled: true },
  { k: "Part Pay", i: Receipt, accent: "gold" as const, enabled: true },
  { k: "Gift Card", i: Gift, accent: "muted" as const, enabled: false },
];
const SPLIT_METHODS = ["Cash", "M-Pesa", "Airtel Money", "Card", "Bank Transfer", "Cheque", "Credit"];

function isCreditMethod(name: string) {
  const key = name.trim().toLowerCase().replace(/_/g, " ");
  return key === "credit" || key === "credit sale" || key === "on account" || key === "customer credit";
}
const QUICK_AMOUNTS = [500, 1000, 2000, 5000] as const;

function POS() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const actions = Array.isArray(user?.effective_permissions) ? user.effective_permissions.map(String) : null;
  const canChooseBatch = actions
    ? actions.includes("inventory.sales.override_fifo")
    : ["admin", "superadmin"].includes(String(user?.role || "").toLowerCase());
  const role = String(user?.role || "");
  const canDate = ["admin", "superadmin", "manager"].includes(role);
  const canRequestDate = canDate || role === "cashier";
  const canRequestPrice = role === "cashier" || role === "manager";
  const [priceRequestOpen, setPriceRequestOpen] = useState(false);
  const [priceRequestType, setPriceRequestType] = useState("price_override");
  const [priceRequestAbout, setPriceRequestAbout] = useState("");
  const [priceRequestAmount, setPriceRequestAmount] = useState("");
  const [priceRequestReason, setPriceRequestReason] = useState("");
  async function submitPriceRequest() {
    if (priceRequestReason.trim().length < 3) {
      toast.error("Enter a reason for this request.");
      return;
    }
    const res = await POST<{ success?: boolean; error?: string; message?: string }>("/approvals", {
      type: priceRequestType,
      title: priceRequestAbout.trim() || (priceRequestType === "large_discount" ? "Discount" : "Price correction"),
      details: priceRequestReason.trim(),
      amount: Number(priceRequestAmount || 0),
    });
    if (!res?.success) {
      toast.error(res?.error || "The request was not sent.");
      return;
    }
    toast.success(res.message || "Waiting for approval. The permanent price was not changed.");
    setPriceRequestOpen(false);
    setPriceRequestAbout("");
    setPriceRequestAmount("");
    setPriceRequestReason("");
  }
  const [backdateReason, setBackdateReason] = useState("");
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<Line[]>([]);
  const [held, setHeld] = useState<Line[] | null>(readHeldSale);
  const [discount, setDiscount] = useState(0);
  const [payment, setPayment] = useState("Cash");
  const [mpesaPhone, setMpesaPhone] = useState("");
  const [mpesaProfile, setMpesaProfile] = useState("");
  const [mpesaCode, setMpesaCode] = useState("");
  const [mpesaPayment, setMpesaPayment] = useState<Record<string, any> | null>(null);
  const mpesaKey = useRef("");
  const [amount, setAmount] = useState("");
  const [splitLines, setSplitLines] = useState<{ method: string; amount: string; reference: string }[]>([
    { method: "M-Pesa", amount: "", reference: "" },
  ]);
  const [remainderOnCredit, setRemainderOnCredit] = useState(false);
  const [qtyDraft, setQtyDraft] = useState<Record<string, string>>({});
  const [copyOpen, setCopyOpen] = useState(false);
  const [cartWide, setCartWide] = useState(false);
  const [note, setNote] = useState("");
  const [lastSaleId, setLastSaleId] = useState<number | null>(null);
  const [docOpen, setDocOpen] = useState(false);
  const [docNotice, setDocNotice] = useState("");
  const [saleDate, setSaleDate] = useState(shopTodayISO);
  const [showNote, setShowNote] = useState(false);
  const [favorites, setFavorites] = useState<Set<number>>(() => new Set());
  const [favOnly, setFavOnly] = useState(false);
  const [recentOnly, setRecentOnly] = useState(false);
  const [recentIds, setRecentIds] = useState<number[]>([]);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [page, setPage] = useState(1);
  const [customerId, setCustomerId] = useState<number | "">("");
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newSaving, setNewSaving] = useState(false);
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
  const mpesaProfilesQ = useQuery({
    queryKey: ["mpesa-profiles"],
    queryFn: () => GET<{ profiles?: Array<Record<string, string>> }>("/mpesa/profiles"),
    enabled: payment === "M-Pesa" || payment === "Split",
  });
  useEffect(() => {
    if (mpesaProfile) return;
    const rows = mpesaProfilesQ.data?.profiles || [];
    const active = rows.filter((row) => row.status === "active");
    const chosen = active.find((row) => {
      const flag = row.is_default;
      return String(flag) === "true" || String(flag) === "1";
    }) || active[0];
    if (chosen?.id) setMpesaProfile(String(chosen.id));
  }, [mpesaProfilesQ.data, mpesaProfile]);
  useEffect(() => {
    const id = mpesaPayment?.id;
    const state = String(mpesaPayment?.state || "");
    if (!id || ["verified", "failed", "cancelled", "timeout", "rejected", "recorded"].includes(state)) return;
    const timer = window.setInterval(async () => {
      const next = await POST<Record<string, any>>(`/mpesa/payments/${id}/poll`, {});
      if (next && !next.error) setMpesaPayment(next);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [mpesaPayment?.id, mpesaPayment?.state]);
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
  const creditNeedsCustomer = payment === "Credit" || payment === "Part Pay"
    || (payment === "Split" && (remainderOnCredit || splitLines.some((row) => isCreditMethod(row.method))));
  const showNewCustomer = creditNeedsCustomer && customerId === "";

  const categories = useMemo(() => {
    const names = new Set<string>();
    let blank = false;
    for (const product of products) {
      const name = (product.category || "").trim();
      if (name) names.add(name);
      else blank = true;
    }
    return [
      "",
      ...Array.from(names).sort((a, b) => a.localeCompare(b)),
      ...(blank ? ["Uncategorised"] : []),
    ];
  }, [products]);

  const filtered = useMemo(() => {
    return products.filter((p) => {
      const rawCategory = (p.category || "").trim();
      const matchCat = !cat || (cat === "Uncategorised" ? !rawCategory : rawCategory === cat);
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
  const splitMoney = payment === "Split"
    ? Math.round(splitLines.reduce((sum, row) => sum + (isCreditMethod(row.method) ? 0 : (parseFloat(row.amount) || 0)), 0) * 100) / 100
    : 0;
  const splitCreditLines = payment === "Split"
    ? Math.round(splitLines.reduce((sum, row) => sum + (isCreditMethod(row.method) ? (parseFloat(row.amount) || 0) : 0), 0) * 100) / 100
    : 0;
  const splitUnallocated = payment === "Split"
    ? Math.round((total - splitMoney - splitCreditLines) * 100) / 100
    : 0;
  const splitCredit = splitCreditLines + (remainderOnCredit && splitUnallocated > 0.009 ? splitUnallocated : 0);
  const splitLineTotal = Math.round((splitMoney + splitCreditLines) * 100) / 100;
  const splitRemaining = splitUnallocated;
  const tendered = payment === "Split" ? splitLineTotal : paid;
  const change = Math.max(0, (payment === "Split" ? tendered : paid) - total);
  const itemCount = cart.reduce((s, l) => s + l.quantity, 0);
  const showTender = payment === "Cash" || payment === "Split" || payment === "M-Pesa" || payment === "Part Pay";

  useEffect(() => {
    const dirty = cart.length > 0 || splitLines.some((row) => (parseFloat(row.amount) || 0) > 0);
    window.dispatchEvent(new CustomEvent("mbt-unsaved", { detail: dirty }));
  }, [cart, splitLines]);

  const placeProduct = async (
    p: { id: number; name: string; sku?: string; unit?: string; price?: number; stock?: number; allow_decimal_qty?: number | null },
    quantity: number,
  ) => {
    const quote = await GET<any>(`/products/${p.id}/sell-quote`, { qty: String(quantity) });
    const quoted = Array.isArray(quote?.lines) ? quote.lines : [];
    const built: Line[] = quoted.length
      ? quoted.map((line: any) => ({
          line_id: line.split ? `b${(line.batch_refs || []).join("-")}` : `p${p.id}`,
          product_id: p.id,
          product_name: line.label || p.name,
          sku: p.sku || "",
          unit: p.unit || "pcs",
          allow_decimal_qty: p.allow_decimal_qty,
          quantity: Number(line.quantity) || 0,
          unit_price: Number(line.unit_price) || 0,
          discount: 0,
          total: lineTotal(Number(line.unit_price) || 0, Number(line.quantity) || 0, 0),
          batch_priced: Boolean(line.split),
        }))
      : [{
          product_id: p.id,
          product_name: p.name,
          sku: p.sku || "",
          unit: p.unit || "pcs",
          allow_decimal_qty: p.allow_decimal_qty,
          quantity,
          unit_price: Number(p.price) || 0,
          discount: 0,
          total: lineTotal(Number(p.price) || 0, quantity, 0),
        }];
    setCart((current) => [
      ...current.filter((line) => line.product_id !== p.id || line.fifo_override),
      ...built,
    ]);
  };

  const chooseBatch = async (line: Line) => {
    const history = await GET<any>(`/products/${line.product_id}/history`);
    const batches = (history?.batches || []).filter((batch: any) => Number(batch.remaining_qty) > 0);
    if (!batches.length) {
      toast.error("This product has no batch with stock left.");
      return;
    }
    const fifo = await GET<any>(`/products/${line.product_id}/sell-quote`, { qty: String(line.quantity) });
    const fifoText = (fifo?.lines || []).map((part: any) => `${part.quantity} at ${part.unit_price}`).join(", ") || "the oldest batch";
    const listed = batches.map((batch: any) => `${batch.batch_ref} left ${batch.remaining_qty} sells ${batch.effective_sell_price}`).join("\n");
    const picked = window.prompt(`FIFO would sell ${fifoText}.\n${listed}\n\nType the batch reference to sell instead.`, batches[0].batch_ref);
    if (!picked) return;
    const batch = batches.find((item: any) => String(item.batch_ref).toLowerCase() === picked.trim().toLowerCase());
    if (!batch) {
      toast.error("That batch was not found.");
      return;
    }
    const qtyText = window.prompt("Quantity from this batch", String(Math.min(line.quantity, Number(batch.remaining_qty))));
    if (qtyText == null) return;
    const quantity = Number(qtyText);
    if (!Number.isFinite(quantity) || quantity <= 0 || quantity > Number(batch.remaining_qty) + 0.0001) {
      toast.error("That batch does not have enough stock left.");
      return;
    }
    const reason = window.prompt("Why is this batch being sold first?");
    if (!reason || reason.trim().length < 3) {
      toast.error("Enter a reason. The batch was not chosen.");
      return;
    }
    const result = await POST<any>(`/products/${line.product_id}/batch-allocation`, {
      picks: [{ layer_id: batch.id, quantity }],
      reason: reason.trim(),
    });
    if (!result || result.error) {
      toast.error(result?.error || "The batch was not chosen.");
      return;
    }
    const rest = Math.round((line.quantity - quantity) * 10000) / 10000;
    const chosen: Line[] = (result.lines || []).map((part: any) => ({
      line_id: `o${part.layer_id}`,
      product_id: line.product_id,
      product_name: part.label || line.product_name,
      sku: line.sku,
      unit: line.unit,
      quantity: Number(part.quantity) || 0,
      unit_price: Number(part.unit_price) || 0,
      discount: 0,
      total: lineTotal(Number(part.unit_price) || 0, Number(part.quantity) || 0, 0),
      batch_priced: true,
      fifo_override: true,
      layer_id: part.layer_id,
      override_reason: reason.trim(),
    }));
    setCart((current) => current.filter((item) => lineKey(item) !== lineKey(line)));
    if (rest > 0.0001) {
      await placeProduct({
        id: line.product_id,
        name: line.product_name.split(" · B")[0],
        sku: line.sku,
        unit: line.unit,
        price: line.unit_price,
      }, rest);
    }
    setCart((current) => [...current, ...chosen]);
    toast.success(`FIFO would sell ${fifoText}. This line sells ${batch.batch_ref} instead.`);
  };

  const add = (p: Product) => {
    if (Number(p.stock) <= 0) return;
    setRecentIds((ids) => [p.id, ...ids.filter((id) => id !== p.id)].slice(0, 24));
    const current = cart
      .filter((line) => line.product_id === p.id && !line.fifo_override)
      .reduce((sum, line) => sum + line.quantity, 0);
    const quantity = current ? snapQty(current + saleQtyStep(p.unit, qtyStep, p.allow_decimal_qty)) : 1;
    if (quantity > Number(p.stock) + 0.0001) {
      toast.error(`Only ${p.stock} in stock`);
      return;
    }
    void placeProduct(p, quantity);
  };

  const setQty = (key: string, productId: number, quantity: number, stock?: number) => {
    const line = cart.find((l) => lineKey(l) === key);
    const parsed = parseQuantity(quantity, line?.unit, { allowZero: true, decimalQty: line?.allow_decimal_qty });
    if ("error" in parsed) {
      const name = line?.product_name || "This product";
      toast.error(parsed.error.includes("whole units") ? `${name} is sold in whole units.` : parsed.error);
      return;
    }
    const next = parsed.quantity <= 0 ? 0 : parsed.quantity;
    const others = cart
      .filter((l) => lineKey(l) !== key && l.product_id === productId)
      .reduce((sum, l) => sum + l.quantity, 0);
    if (stock != null && others + next > Number(stock) + 0.0001) {
      toast.error(`Only ${stock} in stock`);
      return;
    }
    const total = others + next;
    if (total <= 0) {
      setCart((c) => c.filter((l) => l.product_id !== productId));
      return;
    }
    const baseName = (line?.product_name || "Product").split(" · B")[0];
    void placeProduct({
      id: productId,
      name: baseName,
      sku: line?.sku,
      unit: line?.unit,
      allow_decimal_qty: line?.allow_decimal_qty,
      price: line?.unit_price,
      stock,
    }, total);
  };

  const setLineDiscount = (key: string, d: number) =>
    setCart((c) =>
      c.map((l) => {
        if (lineKey(l) !== key) return l;
        const discountAmt = Math.max(0, Math.min(d, l.unit_price * l.quantity));
        return { ...l, discount: discountAmt, total: lineTotal(l.unit_price, l.quantity, discountAmt) };
      }),
    );

  const setLinePrice = (key: string, price: number) =>
    setCart((c) =>
      c.map((l) => {
        if (lineKey(l) !== key) return l;
        const unit = Math.max(0, Math.round((Number(price) || 0) * 100) / 100);
        const discountAmt = Math.max(0, Math.min(l.discount || 0, unit * l.quantity));
        return { ...l, unit_price: unit, discount: discountAmt, total: lineTotal(unit, l.quantity, discountAmt) };
      }),
    );

  const applyCopiedLines = (
    lines: CopiedLine[],
    meta: { replace: boolean; customerId?: number; receipt: string },
  ) => {
    setCart((current) => (meta.replace || current.length === 0 ? lines : [...current, ...lines]));
    if ((meta.replace || cart.length === 0) && meta.customerId) setCustomerId(meta.customerId);
    setNote((prev) => {
      const tag = meta.receipt;
      return prev.trim() ? `${prev.trim()} | ${tag}` : tag;
    });
    setCartWide(true);
    toast.success(`${meta.receipt} added. Edit any line before completing the sale.`);
  };

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
    localStorage.setItem(HELD_KEY, JSON.stringify(cart));
    setCart([]);
    toast.success("Sale held");
  };

  const restoreHeld = () => {
    if (!held?.length) return;
    setCart(held);
    setHeld(null);
    localStorage.removeItem(HELD_KEY);
    toast.success("Held sale restored");
  };

  const clearCart = () => {
    setCart([]);
    setDiscount(0);
    setAmount("");
    setSplitLines([{ method: "M-Pesa", amount: "", reference: "" }]);
    setRemainderOnCredit(false);
    setNote("");
    setCustomerId("");
  };

  const checkout = useMutation({
    mutationFn: async () => {
      if (!cart.length) throw new Error("Add items first");
      const promptState = String(mpesaPayment?.state || "");
      if (["sending", "prompt_sent", "waiting", "unknown", "preparing"].includes(promptState)) {
        throw new Error("The phone prompt is not verified yet. The sale was not completed.");
      }
      if (payment === "Gift Card") throw new Error("Gift Card is not available yet");
      const method =
        payment === "Split" ? "Mixed"
        : payment === "Bank" ? "Bank Transfer"
        : payment === "Credit" ? "Credit Sale"
        : payment === "Part Pay" ? "Part Payment"
        : payment;
      const splitTenders = payment === "Split"
        ? splitLines
          .map((row) => {
            const amount = Math.round((parseFloat(row.amount) || 0) * 100) / 100;
            const creditLine = isCreditMethod(row.method);
            const item: { method: string; amount: number; reference?: string; status?: string } = {
              method: creditLine ? "Credit" : row.method,
              amount,
            };
            if (creditLine) item.status = "outstanding";
            else if (row.reference.trim() && row.method !== "Cash") item.reference = row.reference.trim();
            return item;
          })
          .filter((row) => row.amount > 0)
        : [];
      let activeCustomer: number | "" = customerId;
      const namedCredit = payment === "Split" && splitLines.some((row) => isCreditMethod(row.method) && (parseFloat(row.amount) || 0) > 0);
      const creditSale = payment === "Credit" || payment === "Part Pay" || remainderOnCredit || namedCredit;
      if (creditSale && !activeCustomer && newName.trim()) {
        const phone = newPhone.trim();
        const digits = phone.replace(/\D/g, "");
        if (phone && (digits.length < 9 || digits.length > 15)) {
          throw new Error("Enter a valid phone number or leave it blank.");
        }
        const created = await POST<{ success?: boolean; customer_id?: number; error?: string }>("/customers", {
          name: newName.trim(),
          phone,
        });
        if (!created?.success || !created.customer_id) throw new Error(created?.error || "Could not save the customer.");
        activeCustomer = created.customer_id;
      }
      const splitCollected = Math.round(splitTenders.reduce((sum, row) => sum + (isCreditMethod(row.method) ? 0 : row.amount), 0) * 100) / 100;
      const explicitCredit = Math.round(splitTenders.reduce((sum, row) => sum + (isCreditMethod(row.method) ? row.amount : 0), 0) * 100) / 100;
      const creditLeft = Math.round((total - splitCollected - explicitCredit) * 100) / 100;
      if (payment === "Split") {
        if (remainderOnCredit) {
          if (creditLeft <= 0.009) throw new Error("Those payments already cover the total");
          splitTenders.push({ method: "Credit", amount: creditLeft, status: "outstanding" });
        } else if (creditLeft > 0.009) {
          throw new Error("Payments do not cover the total. Choose Credit for the unpaid amount, or tick On account.");
        } else if (creditLeft < -0.009) {
          const cash = splitTenders.filter((row) => row.method === "Cash").reduce((sum, row) => sum + row.amount, 0);
          if (cash + 0.009 < Math.abs(creditLeft)) throw new Error("Change can only come from cash");
        }
        if (!splitTenders.length) throw new Error("Add at least one payment");
        const owes = splitTenders.filter((row) => isCreditMethod(row.method)).reduce((sum, row) => sum + row.amount, 0);
        if (owes > 0.009 && !activeCustomer) {
          throw new Error("Choose a customer, or enter a new customer name. Customer credit is the amount still owed, not money received.");
        }
      }
      const mixedCash = splitTenders.filter((row) => row.method === "Cash").reduce((sum, row) => sum + row.amount, 0);
      const mixedElectronic = splitTenders
        .filter((row) => row.method !== "Cash" && row.method !== "Credit")
        .reduce((sum, row) => sum + row.amount, 0);
      const mixedMethod = splitTenders.find((row) => row.method !== "Cash" && row.method !== "Credit")?.method || "";
      if ((payment === "Credit" || payment === "Part Pay" || remainderOnCredit) && !activeCustomer) {
        throw new Error("Choose a customer before a credit or part payment, or enter a new customer name.");
      }
      if (payment === "Part Pay" && (!(paid > 0) || paid >= total)) {
        throw new Error("Part payment must be more than zero and less than the total");
      }
      if (method !== "Credit Sale" && method !== "Part Payment" && method !== "Mixed" && paid < total && showTender) {
        throw new Error("Amount paid is less than total");
      }
      const tender = method === "Credit Sale" ? 0
        : method === "Part Payment" ? paid
        : method === "Mixed" ? (remainderOnCredit ? splitCollected : splitLineTotal)
        : (paid || total);
      const pastDate = saleDate && saleDate < shopTodayISO();
      if (pastDate && !canDate) {
        const reason = normalizeBackdateReason(backdateReason);
        if (reason.length < 3 || reason === "Other") {
          throw new Error("Choose a reason for this past date. If you choose Other, write what happened. The sale was not recorded.");
        }
        const created = await POST<any>("/backdate-requests", {
          business_date: saleDate,
          reason,
          sales: [{
            customer_id: activeCustomer || undefined,
            payment_method: method,
            amount_paid: tender,
            cash_paid: method === "Mixed" ? mixedCash : method === "Cash" ? tender : 0,
            electronic_paid: method === "Mixed" ? mixedElectronic : method === "M-Pesa" ? tender : 0,
            notes: note || undefined,
            lines: cart.map((line) => ({
              product_id: line.product_id,
              product_name: line.product_name,
              quantity: line.quantity,
              unit_price: line.unit_price,
              discount: line.discount || 0,
            })),
          }],
        });
        if (!created || created.error || !created.id) throw new Error(created?.error || "The request was not saved.");
        const submitted = await POST<any>(`/backdate-requests/${created.id}/submit`, { version: created.version });
        if (!submitted || submitted.error) throw new Error(submitted?.error || "The request was saved but not submitted.");
        return { success: true, receipt_number: submitted.reference, request: true as const };
      }
      const res = await POST<{ success?: boolean; error?: string; receipt_number?: string; sale_id?: number }>(
        "/sales",
        {
          items: cart,
          subtotal,
          discount: disc,
          tax,
          total,
          payment_method: remainderOnCredit ? "part payment" : (method.toLowerCase() === "mixed" ? "Mixed" : method.toLowerCase()),
          amount_paid: tender,
          change_amount: method === "Credit Sale" || method === "Part Payment" || remainderOnCredit ? 0 : Math.max(0, tender - total),
          cash_paid: method === "Mixed" ? mixedCash : method === "Cash" ? tender : 0,
          electronic_paid: method === "Mixed" ? mixedElectronic : 0,
          electronic_method: method === "Mixed" ? mixedMethod || undefined : undefined,
          payment_tenders: payment === "Split" ? splitTenders
            : payment === "Part Pay" ? [
              { method: "Cash", amount: paid, status: "confirmed" },
              { method: "Credit", amount: Math.round((total - paid) * 100) / 100, status: "outstanding" },
            ] : undefined,
          note: note || undefined,
          mpesa_ref: (payment === "M-Pesa" || payment === "Split")
            ? (mpesaCode || (mpesaPayment?.state === "verified" ? mpesaPayment.receipt_code : undefined))
            : undefined,
          mpesa_payment_id: (payment === "M-Pesa" || payment === "Split") && mpesaPayment?.state === "verified"
            ? mpesaPayment.id
            : undefined,
          customer_id: activeCustomer || undefined,
          sale_date: canDate && saleDate !== shopTodayISO() ? saleDate : undefined,
          client_token: saleTokenRef.current || (saleTokenRef.current = crypto.randomUUID()),
        },
      );
      if (res && (res as { code?: string }).code === "batch_price_review") {
        const lines = (res as { lines?: Array<{ product_id: number; product_name?: string; segments?: Array<{ layer_id: number; batch_ref?: string; quantity: number; unit_price: number }> }> }).lines || [];
        const ids = new Set(lines.map((line) => line.product_id));
        setCart((current) => {
          const kept = current.filter((line) => !ids.has(line.product_id));
          const added = lines.flatMap((line) => (line.segments || []).map((part) => ({
            line_id: `b${part.layer_id}`,
            product_id: line.product_id,
            product_name: `${line.product_name || "Product"} · ${part.batch_ref || part.layer_id}`,
            sku: "",
            quantity: part.quantity,
            unit_price: part.unit_price,
            discount: 0,
            total: Math.round(part.quantity * part.unit_price * 100) / 100,
            batch_priced: true,
          })));
          return [...kept, ...added];
        });
        throw new Error(res.error || "Review the batch prices, then take payment again.");
      }
      if (!res?.success) throw new Error(res?.error || "Sale failed");
      return { ...res, request: false as const };
    },
    onSuccess: (res) => {
      toast.success(res.request
        ? `Request ${res.receipt_number} is waiting for approval. The sale was not recorded.`
        : `Sale recorded — ${res.receipt_number}`);
      if (res.request) {
        setSaleDate(shopTodayISO());
        setBackdateReason("");
      }
      if (!res.request && res.sale_id) {
        setLastSaleId(res.sale_id);
        void POST<any>(`/sales/${res.sale_id}/document/print`, { automatic: true, reprint: false }).then((printed) => {
          const failed = printed && !printed.printed && !printed.skipped && printed.message;
          setDocNotice(failed ? printed.message : "");
          setDocOpen(true);
        });
      }
      saleTokenRef.current = "";
      setNewName("");
      setNewPhone("");
      const sold = new Map<number, number>();
      if (!res.request) {
        for (const line of cart) {
          sold.set(line.product_id, (sold.get(line.product_id) || 0) + Number(line.quantity || 0));
        }
      }
      clearCart();
      searchRef.current?.focus();
      if (sold.size) {
        qc.setQueryData(["products"], (old: unknown) => {
          if (!Array.isArray(old)) return old;
          return old.map((product) => {
            const qty = sold.get(Number(product?.id));
            if (qty == null) return product;
            const next = Math.round((Number(product.stock || 0) - qty) * 10000) / 10000;
            return { ...product, stock: next };
          });
        });
      }
      qc.invalidateQueries({ queryKey: ["products"] });
      qc.invalidateQueries({ queryKey: ["sales-today"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  async function openLastReceipt(print: boolean) {
    if (!lastSaleId) {
      toast.message("Complete a sale on this screen first. Older receipts open from All Receipts.");
      return;
    }
    if (!print) {
      setDocNotice("");
      setDocOpen(true);
      return;
    }
    const printed = await POST<any>(`/sales/${lastSaleId}/document/print`, { automatic: false, reprint: true });
    setDocNotice(printed?.printed ? "" : (printed?.message || "Sale saved successfully. Printer unavailable. You can view, download or print the document later."));
    setDocOpen(true);
  }

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
                  <div key={lineKey(l)} className="px-2 py-1.5 flex items-center gap-1.5">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-text truncate">{l.product_name}</div>
                      {canChooseBatch && !l.fifo_override ? (
                        <button type="button" className="text-[10px] font-semibold text-primary" onClick={() => void chooseBatch(l)}>
                          Choose batch
                        </button>
                      ) : null}
                      <div className="text-[10px] text-muted-fg font-mono truncate">
                        {l.sku || `#${l.product_id}`}
                      </div>
                    </div>
                    <input
                      type="number"
                      min={0}
                      step={1}
                      value={l.unit_price}
                      onChange={(e) => setLinePrice(lineKey(l), parseFloat(e.target.value) || 0)}
                      className="h-8 w-16 rounded-lg border border-border bg-input px-1 text-[12px] font-bold text-right text-text tabular-nums shrink-0"
                      title={`Price (${currency})`}
                      aria-label={`Price for ${l.product_name}`}
                    />
                    <div className="inline-flex items-center rounded-lg border border-border bg-input shrink-0">
                      <button
                        type="button"
                        aria-label="Decrease"
                        onClick={() => setQty(lineKey(l), l.product_id, l.quantity - saleQtyStep(l.unit, qtyStep, l.allow_decimal_qty), products.find((p) => p.id === l.product_id)?.stock)}
                        className="h-8 w-8 grid place-items-center text-text hover:bg-hover"
                      >
                        <Minus className="h-3.5 w-3.5" />
                      </button>
                      <input
                        type="number"
                        min={0.01}
                        step={saleQtyStep(l.unit, qtyStep, l.allow_decimal_qty)}
                        onWheel={(e) => {
                          if (document.activeElement !== e.currentTarget) return;
                          e.preventDefault();
                          const dir = e.deltaY < 0 ? 1 : -1;
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(lineKey(l), l.product_id, l.quantity + dir * saleQtyStep(l.unit, qtyStep, l.allow_decimal_qty), stock);
                        }}
                        aria-label={`Quantity for ${l.product_name}`}
                        value={qtyDraft[lineKey(l)] ?? formatQty(l.quantity)}
                        onChange={(e) => {
                          const raw = e.target.value;
                          const key = lineKey(l);
                          setQtyDraft((draft) => ({ ...draft, [key]: raw }));
                          const parsed = parseQuantity(raw, l.unit, { decimalQty: l.allow_decimal_qty });
                          if ("error" in parsed) return;
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(key, l.product_id, parsed.quantity, stock);
                        }}
                        onBlur={(e) => {
                          const raw = e.currentTarget.value;
                          const key = lineKey(l);
                          setQtyDraft((draft) => {
                            const next = { ...draft };
                            delete next[key];
                            return next;
                          });
                          if (raw == null || raw.trim() === "") return;
                          const parsed = parseQuantity(raw, l.unit, { decimalQty: l.allow_decimal_qty });
                          if ("error" in parsed) {
                            toast.error(parsed.error.includes("whole units")
                              ? `${l.product_name} is sold in whole units.`
                              : parsed.error);
                            return;
                          }
                          const stock = products.find((p) => p.id === l.product_id)?.stock;
                          setQty(key, l.product_id, parsed.quantity, stock);
                        }}
                        className="h-8 w-14 border-0 bg-transparent text-center text-[13px] font-bold tabular-nums text-text"
                      />
                      <button
                        type="button"
                        aria-label="Increase"
                        onClick={() =>
                          setQty(
                            lineKey(l),
                            l.product_id,
                            l.quantity + saleQtyStep(l.unit, qtyStep, l.allow_decimal_qty),
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
                      onChange={(e) => setLineDiscount(lineKey(l), parseFloat(e.target.value) || 0)}
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
                      onClick={() => setQty(lineKey(l), l.product_id, 0)}
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
            <div className="flex flex-wrap items-center gap-1.5">
              <Select
                value={customerId === "" ? "" : String(customerId)}
                onChange={(e) => {
                  const next = e.target.value ? Number(e.target.value) : "";
                  setCustomerId(next);
                  if (next !== "") {
                    setNewName("");
                    setNewPhone("");
                  }
                }}
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
              {canRequestDate ? (
                <>
                  <button
                    type="button"
                    className="h-8 rounded-lg border border-border px-2 text-xs font-semibold"
                    onClick={() => setCopyOpen(true)}
                  >
                    Copy sale
                  </button>
                  <button
                    type="button"
                    aria-label="Sale date"
                    title={canDate
                      ? "Change the sale date. A past date is recorded on that business day."
                      : "A past date is sent for approval. The sale is not recorded until it is approved."}
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
                  {saleDate < shopTodayISO() ? (
                    <button
                      type="button"
                      className="h-8 rounded-lg border border-border px-2 text-xs font-semibold"
                      onClick={() => { setSaleDate(shopTodayISO()); setBackdateReason(""); }}
                    >
                      Back to today
                    </button>
                  ) : null}
                  {!canDate && saleDate < shopTodayISO() ? (
                    <div className="flex w-full min-w-0 basis-full flex-col gap-1">
                      <p className="text-xs font-semibold text-err">{backdateWarning(saleDate)}</p>
                      <BackdateReasonPicker compact reason={backdateReason} onReason={setBackdateReason} />
                    </div>
                  ) : null}
                </>
              ) : null}
            </div>

            {showNewCustomer ? (
              <div className="rounded-lg border border-gold/50 bg-gold/10 p-2 space-y-1.5">
                <div className="flex items-center gap-1.5 text-[11px] font-extrabold uppercase tracking-wide text-gold">
                  <UserPlus className="h-3.5 w-3.5" />
                  New customer
                </div>
                <p className="text-[11px] leading-snug text-text2">
                  This credit stays on their account. Enter a name, or choose a saved customer above.
                </p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Input
                    aria-label="New customer name"
                    placeholder="Customer name"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="h-8 min-h-0 flex-1 text-xs"
                  />
                  <Input
                    aria-label="New customer phone"
                    placeholder="Phone (optional)"
                    value={newPhone}
                    onChange={(e) => setNewPhone(e.target.value)}
                    className="h-8 min-h-0 w-36 text-xs"
                  />
                  <Button
                    type="button"
                    className="h-8 min-h-0 px-3 text-xs"
                    disabled={newSaving || !newName.trim()}
                    onClick={async () => {
                      const phone = newPhone.trim();
                      const digits = phone.replace(/\D/g, "");
                      if (phone && (digits.length < 9 || digits.length > 15)) {
                        toast.error("Enter a valid phone number or leave it blank.");
                        return;
                      }
                      setNewSaving(true);
                      try {
                        const created = await POST<{ success?: boolean; customer_id?: number; error?: string }>("/customers", {
                          name: newName.trim(),
                          phone,
                        });
                        if (!created?.success || !created.customer_id) {
                          toast.error(created?.error || "Could not save the customer.");
                          return;
                        }
                        setCustomerId(created.customer_id);
                        setNewName("");
                        setNewPhone("");
                        await qc.invalidateQueries({ queryKey: ["customers"] });
                        toast.success("Customer saved. This credit sale will use them.");
                      } finally {
                        setNewSaving(false);
                      }
                    }}
                  >
                    {newSaving ? "Saving…" : "Save and use"}
                  </Button>
                </div>
              </div>
            ) : null}

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

            {payment === "M-Pesa" || payment === "Split" ? (
              <div className="rounded-lg border border-border bg-card2 p-2 space-y-1">
                <div className="text-[11px] font-semibold text-text2">
                  {settingsQ.data?.mpesa_business_name || settingsQ.data?.shop_name || "This shop"}
                  {settingsQ.data?.mpesa_till ? ` · Till ${settingsQ.data.mpesa_till}` : ""}
                  {settingsQ.data?.mpesa_paybill ? ` · Paybill ${settingsQ.data.mpesa_paybill}` : ""}
                  {!settingsQ.data?.mpesa_till && !settingsQ.data?.mpesa_paybill ? " · Set the till or paybill in Settings" : ""}
                </div>
                <div className="grid gap-1">
                  <select
                    aria-label="M-Pesa profile"
                    value={mpesaProfile}
                    onChange={(e) => setMpesaProfile(e.target.value)}
                    className="h-8 w-full rounded-lg border border-border bg-input px-2 text-xs font-semibold text-text"
                  >
                    <option value="">Manual only</option>
                    {(mpesaProfilesQ.data?.profiles || []).filter((row) => row.status === "active").map((row) => (
                      <option key={row.id} value={row.id}>{row.name}</option>
                    ))}
                  </select>
                  <div className="flex items-center gap-1">
                    <Input
                      value={mpesaPhone}
                      onChange={(e) => setMpesaPhone(e.target.value)}
                      placeholder="Customer phone"
                      aria-label="Customer phone for M-Pesa prompt"
                      className="h-8 min-h-0 min-w-0 flex-1 text-xs"
                    />
                    <button
                      type="button"
                      className="h-8 shrink-0 px-2 rounded-lg border border-border text-[11px] font-bold"
                      onClick={() => {
                      if (!mpesaKey.current) mpesaKey.current = crypto.randomUUID();
                      const mpesaDue = payment === "Split"
                        ? splitLines.reduce((sum, row) => (
                          String(row.method || "").toLowerCase().replace(/[-\s]/g, "").includes("mpesa")
                            ? sum + (parseFloat(row.amount) || 0)
                            : sum
                        ), 0)
                        : Number(amount || total);
                      void POST<Record<string, any>>("/mpesa/stk", {
                        phone: mpesaPhone,
                        amount: mpesaDue,
                        profile_id: mpesaProfile,
                        sale_reference: "",
                        idempotency_key: mpesaKey.current,
                      }).then((result) => {
                        if (!result || result.error) {
                          toast.error(result?.error || "The prompt was not sent");
                          return;
                        }
                        setMpesaPayment(result);
                        toast.success(result.customer_message || "Prompt sent. This is not payment yet.");
                      });
                    }}
                  >
                    Send phone prompt
                  </button>
                  </div>
                </div>
                <Input
                  value={mpesaCode}
                  onChange={(e) => setMpesaCode(e.target.value)}
                  placeholder="Manual M-Pesa code, if the customer already paid"
                  aria-label="Manual M-Pesa code"
                  className="h-8 min-h-0 text-xs"
                />
                <p className="text-[11px] text-text2">
                  {mpesaPayment?.customer_message
                    || "A phone prompt is not payment. Manual codes stay unverified until they are matched."}
                </p>
              </div>
            ) : null}

            {payment === "Split" ? (
              <div className="space-y-1">
                {splitLines.map((row, index) => (
                  <div key={index} className="flex items-center gap-1">
                    <select
                      aria-label={`Payment method ${index + 1}`}
                      value={row.method}
                      onChange={(e) => setSplitLines((rows) => rows.map((item, i) => i === index ? { ...item, method: e.target.value } : item))}
                      className="h-8 rounded-lg border border-border bg-input px-2 text-xs font-semibold text-text"
                    >
                      {SPLIT_METHODS.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                    <Input
                      type="number"
                      min={0}
                      step={0.01}
                      placeholder="Amount"
                      aria-label={`Amount ${index + 1}`}
                      value={row.amount}
                      onChange={(e) => setSplitLines((rows) => rows.map((item, i) => i === index ? { ...item, amount: e.target.value } : item))}
                      className="h-8 min-h-0 text-sm font-semibold tabular-nums w-24"
                    />
                    {row.method !== "Cash" && !isCreditMethod(row.method) ? (
                      <Input
                        placeholder="Reference"
                        aria-label={`Reference ${index + 1}`}
                        value={row.reference}
                        onChange={(e) => setSplitLines((rows) => rows.map((item, i) => i === index ? { ...item, reference: e.target.value } : item))}
                        className="h-8 min-h-0 text-xs flex-1"
                      />
                    ) : null}
                    <button
                      type="button"
                      className="h-8 px-2 text-[11px] font-bold text-text2"
                      onClick={() => setSplitLines((rows) => rows.length === 1 ? [{ method: "M-Pesa", amount: "", reference: "" }] : rows.filter((_, i) => i !== index))}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold text-text2">
                  <button
                    type="button"
                    className="underline"
                    onClick={() => setSplitLines((rows) => [...rows, { method: "Card", amount: "", reference: "" }])}
                  >
                    Add payment
                  </button>
                  <label className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={remainderOnCredit}
                      onChange={(e) => setRemainderOnCredit(e.target.checked)}
                    />
                    On account
                  </label>
                  <span className="font-extrabold text-text">
                    {`Sale ${KES(total, currency)} · Paid ${KES(splitMoney, currency)} · Customer credit ${KES(splitCredit, currency)}`}
                    {splitRemaining > 0.009 && !remainderOnCredit
                      ? ` · Still due ${KES(splitRemaining, currency)}`
                      : splitRemaining < -0.009
                        ? ` · Over by ${KES(Math.abs(splitRemaining), currency)}`
                        : ""}
                  </span>
                </div>
                {splitCredit > 0.009 ? (
                  <div className="text-[11px] font-bold text-gold">
                    {customerId
                      ? "Customer credit is the amount still owed. It is not money received."
                      : "Select a customer. Customer credit is the amount still owed, not money received."}
                  </div>
                ) : null}
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
                <span className={cn(
                  "text-[11px] font-extrabold tabular-nums whitespace-nowrap pl-1",
                  payment === "Part Pay" ? "text-gold" : "text-ok",
                )}>
                  {payment === "Part Pay"
                    ? `Paid ${KES(paid, currency)} · Still owed ${KES(Math.max(0, Math.round((total - paid) * 100) / 100), currency)}`
                    : `Change ${KES(change, currency)}`}
                </span>
              </div>
            ) : (
              <div className="text-[11px] text-text2 px-0.5">
                {payment === "Card" || payment === "Bank" || payment === "Airtel Money" || payment === "Cheque"
                  ? "No cash tender. The sale total is collected by this method."
                  : payment === "Credit"
                    ? "Full amount stays on the customer account. Choose a saved customer or enter a new one above."
                    : "Choose a saved customer or enter a new one above, then enter the amount paid now."}
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
          {priceRequestOpen ? (
            <div className="shrink-0 space-y-1 border-t border-border bg-panel px-2 py-2">
              <div className="text-xs font-semibold text-text">Request a discount or price correction. The product price stays as it is.</div>
              <div className="flex flex-wrap gap-1">
                <select aria-label="Request type" value={priceRequestType} onChange={(e) => setPriceRequestType(e.target.value)} className="h-9 rounded-md border border-border bg-card px-2 text-sm">
                  <option value="price_override">Price correction</option>
                  <option value="large_discount">Discount</option>
                </select>
                <input aria-label="Request about" value={priceRequestAbout} onChange={(e) => setPriceRequestAbout(e.target.value)} placeholder="Product or receipt" className="h-9 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-sm" />
                <input aria-label="Request amount" value={priceRequestAmount} onChange={(e) => setPriceRequestAmount(e.target.value)} placeholder="Amount" className="h-9 w-24 rounded-md border border-border bg-card px-2 text-sm" />
                <input aria-label="Request reason" value={priceRequestReason} onChange={(e) => setPriceRequestReason(e.target.value)} placeholder="Reason" className="h-9 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-sm" />
                <button type="button" onClick={() => void submitPriceRequest()} className="h-9 rounded-md bg-gold px-3 text-sm font-semibold text-black">Submit request</button>
              </div>
            </div>
          ) : null}
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
                onClick={() => void openLastReceipt(false)}
                className="h-10 w-10 shrink-0 rounded-lg border border-border bg-card2 text-text2 grid place-items-center"
              >
                <Eye className="h-4 w-4" />
              </button>
              <button
                type="button"
                title="Print receipt"
                onClick={() => void openLastReceipt(true)}
                className="h-10 w-10 shrink-0 rounded-lg border border-border bg-card2 text-text2 grid place-items-center"
              >
                <Printer className="h-4 w-4" />
              </button>
              {canRequestPrice ? (
                <button
                  type="button"
                  title="Request a discount or price correction"
                  onClick={() => setPriceRequestOpen((open) => !open)}
                  className="h-10 shrink-0 rounded-lg border border-border bg-card2 px-2 text-xs font-semibold text-text"
                >
                  Request price
                </button>
              ) : null}
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
      {docOpen && lastSaleId ? (
        <SaleDocumentPanel
          saleId={lastSaleId}
          notice={docNotice}
          currency={currency}
          onClose={() => setDocOpen(false)}
        />
      ) : null}
      {copyOpen ? (
        <CopySaleDialog
          date={saleDate}
          currency={currency}
          products={products}
          onAdd={applyCopiedLines}
          onClose={() => setCopyOpen(false)}
        />
      ) : null}
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
  const src = productPhotoSrc(image, "thumb");
  if (src) {
    return <img src={src} alt="" title={name} className={cn("shrink-0 rounded-xl object-cover", small ? "h-8 w-8" : "h-12 w-12")} />;
  }
  return <ProductPhoto size={small ? "sm" : "md"} />;
}

function qtyText(stock: number) {
  const rounded = Math.round(Number(stock || 0) * 10000) / 10000;
  return String(rounded);
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
      {oos ? "Out of Stock" : low ? `Low · ${qtyText(stock)}` : `${qtyText(stock)} ${unit || "pcs"}`}
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
        {productPhotoSrc(p.image_path || p.image_url, "thumb") ? (
          <img src={productPhotoSrc(p.image_path || p.image_url, "thumb")} alt="" className="h-full w-full object-cover" />
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
