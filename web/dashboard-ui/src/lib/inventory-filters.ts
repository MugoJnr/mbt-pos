/** Inventory list filters. Same stock bands as the till. They do not change records. */

export const UNCATEGORISED = "__uncategorised__";

export type StockBand = "in" | "low" | "out";

export type InventorySort =
  | "name_asc"
  | "name_desc"
  | "stock_asc"
  | "stock_desc"
  | "created"
  | "updated"
  | "price_asc"
  | "price_desc"
  | "category_asc"
  | "category_desc";

type ProductLike = {
  id?: number;
  name?: string;
  sku?: string;
  barcode?: string;
  category?: string;
  price?: number;
  stock?: number | string | null;
  min_stock?: number | string | null;
  created_at?: string;
  updated_at?: string;
};

export function availableQty(product: ProductLike): number {
  const raw = product?.stock;
  if (raw == null || raw === "") return 0;
  const qty = Number(raw);
  return Number.isFinite(qty) ? qty : 0;
}

export function reorderLevel(product: ProductLike): number | null {
  const raw = product?.min_stock;
  if (raw == null || raw === "") return null;
  const level = Number(raw);
  return Number.isFinite(level) ? level : null;
}

export function stockBand(product: ProductLike): StockBand {
  const qty = availableQty(product);
  if (qty <= 0) return "out";
  const level = reorderLevel(product);
  if (level != null && qty <= level) return "low";
  return "in";
}

export function assignedCategory(product: ProductLike): string {
  return String(product?.category || "").replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ");
}

export function catalogMatches(query: string, product: ProductLike): boolean {
  const q = String(query || "").trim().toLowerCase().replace(/\s+/g, " ");
  if (!q) return true;
  return ["name", "sku", "barcode"].some((key) => {
    const text = String((product as Record<string, unknown>)[key] || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, " ");
    return text.includes(q);
  });
}

export function categoryMatches(product: ProductLike, selected: string): boolean {
  const choice = String(selected || "").trim();
  if (!choice || choice === "all") return true;
  const label = assignedCategory(product);
  if (choice === UNCATEGORISED) return label === "";
  return label.toLowerCase() === choice.trim().replace(/\s+/g, " ").toLowerCase();
}

function nameKey(product: ProductLike): string {
  return String(product.name || "").toLowerCase();
}

function pid(product: ProductLike): number {
  const id = Number(product.id || 0);
  return Number.isFinite(id) ? id : 0;
}

export function sortInventory<T extends ProductLike>(products: T[], mode: InventorySort | string = "name_asc"): T[] {
  const rows = [...(products || [])];
  if (mode === "name_desc") {
    rows.sort((a, b) => nameKey(b).localeCompare(nameKey(a)) || pid(b) - pid(a));
  } else if (mode === "stock_asc") {
    rows.sort((a, b) => availableQty(a) - availableQty(b) || nameKey(a).localeCompare(nameKey(b)) || pid(a) - pid(b));
  } else if (mode === "stock_desc") {
    rows.sort((a, b) => availableQty(b) - availableQty(a) || nameKey(a).localeCompare(nameKey(b)) || pid(a) - pid(b));
  } else if (mode === "price_asc") {
    rows.sort((a, b) => Number(a.price || 0) - Number(b.price || 0) || nameKey(a).localeCompare(nameKey(b)));
  } else if (mode === "price_desc") {
    rows.sort((a, b) => Number(b.price || 0) - Number(a.price || 0) || nameKey(a).localeCompare(nameKey(b)));
  } else if (mode === "category_asc") {
    rows.sort((a, b) => assignedCategory(a).localeCompare(assignedCategory(b)) || nameKey(a).localeCompare(nameKey(b)));
  } else if (mode === "category_desc") {
    rows.sort((a, b) => assignedCategory(b).localeCompare(assignedCategory(a)) || nameKey(a).localeCompare(nameKey(b)));
  } else if (mode === "created" || mode === "updated") {
    const field = mode === "created" ? "created_at" : "updated_at";
    const dated = rows.filter((product) => String(product[field] || "").trim());
    const undated = rows.filter((product) => !String(product[field] || "").trim());
    dated.sort((a, b) => nameKey(a).localeCompare(nameKey(b)) || pid(a) - pid(b));
    dated.sort((a, b) => String(b[field]).localeCompare(String(a[field])));
    undated.sort((a, b) => nameKey(a).localeCompare(nameKey(b)) || pid(a) - pid(b));
    return [...dated, ...undated];
  } else {
    rows.sort((a, b) => nameKey(a).localeCompare(nameKey(b)) || pid(a) - pid(b));
  }
  return rows;
}
