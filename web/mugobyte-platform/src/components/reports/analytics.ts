export type AnalyticsTab = "overview" | "sales" | "debts" | "inventory" | "saved";

export type AnalyticsSearch = {
  tab?: AnalyticsTab;
  start?: string;
  end?: string;
};

export type AnalyticsRow = Record<string, unknown>;

export type AnalyticsResponse = {
  error?: string;
  currency?: string;
  page?: number;
  page_size?: number;
  total?: number;
  total_count?: number;
  pages?: number;
  items?: AnalyticsRow[];
  rows?: AnalyticsRow[];
  sales?: AnalyticsRow[];
  debts?: AnalyticsRow[];
  payments?: AnalyticsRow[];
  inventory?: AnalyticsRow[];
  data?: AnalyticsRow[] | Record<string, unknown>;
  [key: string]: unknown;
};

export type ShopPresence = {
  pc_online?: boolean;
  pc_status?: string;
  online_device_count?: number;
  device_count?: number;
  last_seen_at?: string | null;
  last_sync_at?: string | null;
  sync_freshness?: "fresh" | "aging" | "stale" | "never" | string;
  sync_age_seconds?: number | null;
  data_label?: string;
  is_live_data?: boolean;
};

/** Africa/Nairobi calendar day (Kenya-aware). */
export const todayIso = () => {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Africa/Nairobi",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  } catch {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
  }
};

/** Inclusive Nairobi calendar day N days before today (0 = today). */
export const daysAgoIso = (days: number) => {
  const today = todayIso();
  const base = new Date(`${today}T12:00:00+03:00`);
  base.setDate(base.getDate() - Math.max(0, Math.floor(days)));
  return base.toISOString().slice(0, 10);
};

/** Default Reports range: today (Nairobi calendar day). */
export const defaultAnalyticsRange = () => {
  const day = todayIso();
  return { start: day, end: day };
};

const PROFIT_UNAVAILABLE_HINT = "Cost data incomplete — profit unavailable";

/** True when value is absent (null/undefined/""), not when it is numeric zero. */
export function isMissingAmount(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** Display as KSh with Kenyan-friendly grouping. Missing amounts stay "—". */
export function formatMoney(value: unknown, currency = "KES") {
  if (isMissingAmount(value)) return "—";
  const amount = Number(value);
  const code = currency === "KES" || currency === "KSh" ? "KSh" : currency;
  return `${code} ${Number.isFinite(amount) ? amount.toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0.00"}`;
}

/** KPI-safe currency: never mid-number ellipsis; abbreviate large values.
 *  Never coerce null/undefined to KSh 0 (misleading for incomplete profit). */
export function formatCompactMoney(value: unknown, currency = "KES") {
  if (isMissingAmount(value)) return "—";
  const amount = Number(value);
  const code = currency === "KES" || currency === "KSh" ? "KSh" : currency;
  if (!Number.isFinite(amount)) return "—";
  const sign = amount < 0 ? "-" : "";
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) {
    const digits = abs >= 10_000_000 ? 0 : 1;
    return `${code} ${sign}${(abs / 1_000_000).toFixed(digits)}M`;
  }
  if (abs >= 10_000) {
    return `${code} ${sign}${(abs / 1_000).toFixed(1)}K`;
  }
  if (Math.abs(abs - Math.round(abs)) < 0.005) {
    return `${code} ${sign}${Math.round(abs).toLocaleString("en-KE")}`;
  }
  return `${code} ${sign}${abs.toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Gross profit KPI for the selected range — always show a number when present. */
export function profitKpiFromSummary(
  summary: AnalyticsRow,
  profit: unknown,
  margin: unknown,
  currency = "KES",
): { amount: string; hint: string; unavailable: boolean } {
  const message = String(summary.cost_data_message || "").trim();
  const txns = Number(summary.transactions ?? summary.sales_count ?? 0) || 0;
  const salesTotal =
    Number(summary.gross_sales ?? summary.sales_total ?? summary.revenue ?? 0) || 0;
  const hasSalesActivity = txns > 0 || salesTotal > 0;

  if (isMissingAmount(profit) && !hasSalesActivity) {
    return { amount: "—", hint: "No sales in range", unavailable: false };
  }
  // Prefer API profit; if somehow null with sales, show 0 not a blank dash.
  const amountValue = isMissingAmount(profit) ? 0 : profit;
  return {
    amount: formatCompactMoney(amountValue, currency),
    hint:
      margin != null && margin !== ""
        ? `${formatNumber(margin, 1)}% margin`
        : message || "Sales − cost for selected range",
    unavailable: false,
  };
}

export function formatNumber(value: unknown, digits = 0) {
  const amount = Number(value || 0);
  return Number.isFinite(amount)
    ? amount.toLocaleString("en-KE", { maximumFractionDigits: digits })
    : "0";
}

export function formatDateTime(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("en-KE", {
        timeZone: "Africa/Nairobi",
        dateStyle: "medium",
        timeStyle: "short",
      });
}

export function formatRelativeSync(value: unknown, nowMs = Date.now()) {
  if (!value) return "Never synced";
  const ts = new Date(String(value)).getTime();
  if (!Number.isFinite(ts)) return String(value);
  const delta = Math.max(0, Math.floor((nowMs - ts) / 1000));
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export function value(row: AnalyticsRow, ...keys: string[]): unknown {
  for (const key of keys) {
    const found = row[key];
    if (found !== undefined && found !== null && found !== "") return found;
  }
  return undefined;
}

export function rowsOf(response: AnalyticsResponse | null | undefined, ...keys: string[]) {
  if (!response) return [];
  for (const key of keys) {
    const candidate = response[key];
    if (Array.isArray(candidate)) return candidate as AnalyticsRow[];
  }
  if (Array.isArray(response.data)) return response.data as AnalyticsRow[];
  return [];
}

export function paginationOf(response: AnalyticsResponse | null | undefined, rowCount: number) {
  const total = Number(response?.total ?? response?.total_count ?? rowCount);
  const page = Math.max(1, Number(response?.page || 1));
  const pageSize = Math.max(1, Number(response?.page_size || 25));
  return { total, page, pageSize, pages: Math.max(1, Number(response?.pages || Math.ceil(total / pageSize))) };
}

export function statusVariant(status: unknown): "default" | "secondary" | "destructive" | "outline" {
  const normalized = String(status || "").toLowerCase();
  if (["paid", "completed", "in stock", "active"].includes(normalized)) return "default";
  if (["void", "voided", "cancelled", "overdue", "out of stock"].includes(normalized)) return "destructive";
  if (["pending", "partial", "low stock"].includes(normalized)) return "secondary";
  return "outline";
}
