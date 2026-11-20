import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui-kit";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";

type ReceiptRow = {
  kind: string;
  id: number;
  reference: string;
  amount?: number | null;
  status?: string;
  display_status?: string;
  summary?: string;
};

type SaleLine = {
  product_id?: number;
  product_name?: string;
  sku?: string;
  quantity?: number;
  unit_price?: number;
  discount?: number;
};

type Detail = {
  reference?: string;
  header?: { status?: string };
  customer?: { id?: number } | null;
  lines?: SaleLine[];
  error?: string;
};

export type CopiedLine = {
  line_id: string;
  product_id: number;
  product_name: string;
  sku: string;
  unit?: string;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
};

type ProductHint = { id: number; name: string; sku?: string; unit?: string };

export function CopySaleDialog({
  date,
  currency,
  products,
  onAdd,
  onClose,
}: {
  date: string;
  currency: string;
  products: ProductHint[];
  onAdd: (lines: CopiedLine[], meta: { replace: boolean; customerId?: number; receipt: string }) => void;
  onClose: () => void;
}) {
  const [notice, setNotice] = useState("Pick a receipt. You can add more than one, then edit each line in the cart.");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<number[]>([]);
  const listQ = useQuery({
    queryKey: ["copy-sales", date],
    queryFn: () => GET<{ receipts?: ReceiptRow[]; error?: string }>("/receipts", {
      start: date,
      end: date,
      type: "sale",
      limit: "100",
    }),
  });
  const sales = (listQ.data?.receipts || []).filter((row) => {
    if (row.kind !== "sale") return false;
    const status = (row.status || "").toLowerCase();
    const shown = (row.display_status || "").toLowerCase();
    return status !== "voided" && shown !== "voided";
  });

  async function copyOne(id: number, replace: boolean) {
    setBusy(true);
    try {
      const detail = await GET<Detail>(`/receipts/sale/${id}`);
      if (!detail || detail.error) throw new Error(detail?.error || "Could not open that sale.");
      const status = String(detail.header?.status || "completed").toLowerCase();
      if (status !== "completed" && status !== "") {
        setNotice("Only a completed sale can be copied.");
        return;
      }
      const lines: CopiedLine[] = [];
      (detail.lines || []).forEach((item, index) => {
        const productId = Number(item.product_id || 0);
        const quantity = Number(item.quantity || 0);
        if (!productId || quantity <= 0) return;
        const product = products.find((row) => row.id === productId);
        const price = Number(item.unit_price || 0);
        const discount = Math.max(0, Math.min(Number(item.discount || 0), price * quantity));
        lines.push({
          line_id: `copy-${id}-${index}-${added.length}-${lines.length}`,
          product_id: productId,
          product_name: item.product_name || product?.name || "",
          sku: item.sku || product?.sku || "",
          unit: product?.unit || "pcs",
          quantity,
          unit_price: price,
          discount,
          total: Math.round((price * quantity - discount) * 100) / 100,
        });
      });
      if (!lines.length) {
        setNotice("That sale has no products that can be copied.");
        return;
      }
      const receipt = detail.reference || `sale #${id}`;
      onAdd(lines, { replace, customerId: detail.customer?.id, receipt });
      setAdded((ids) => (ids.includes(id) ? ids : [...ids, id]));
      setNotice(`${receipt} is in the cart. Change quantity, price or discount, or add another receipt.`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not open that sale.");
    } finally {
      setBusy(false);
    }
  }

  async function copyRest() {
    const pending = sales.filter((sale) => !added.includes(sale.id));
    if (!pending.length) {
      setNotice("Every sale for this day is already in the cart.");
      return;
    }
    for (const sale of pending) {
      await copyOne(sale.id, false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl border border-border bg-panel p-4"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-text">Copy a sale</h2>
        <p className="mt-1 text-xs text-text2">
          Receipts for {date}. A copied sale keeps its products, quantities, prices and discounts.
          Adding another receipt leaves the earlier lines in the cart.
        </p>
        <div className="mt-3 min-h-0 flex-1 space-y-1 overflow-y-auto">
          {listQ.isLoading ? <p className="text-sm text-text2">Loading sales…</p> : null}
          {!listQ.isLoading && sales.length === 0 ? (
            <p className="text-sm text-text2">No completed sales on this date.</p>
          ) : null}
          {sales.map((sale) => (
            <div key={sale.id} className="flex items-center gap-2 rounded-xl border border-border px-2 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-text">{sale.reference}</div>
                <div className="truncate text-xs text-text2">{sale.summary || "No products listed"}</div>
              </div>
              <div className="text-xs font-bold tabular-nums text-text">{KES(Number(sale.amount || 0), currency)}</div>
              <Button type="button" className="min-h-9 px-2" disabled={busy} onClick={() => copyOne(sale.id, false)}>
                {added.includes(sale.id) ? "Add again" : "Add"}
              </Button>
              <Button type="button" variant="secondary" className="min-h-9 px-2" disabled={busy} onClick={() => copyOne(sale.id, true)}>
                Replace
              </Button>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-text2">{notice}</p>
        <div className="mt-3 flex justify-end gap-2">
          <Button type="button" variant="secondary" disabled={busy || sales.length === 0} onClick={copyRest}>
            Add every sale this day
          </Button>
          <Button type="button" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
}
