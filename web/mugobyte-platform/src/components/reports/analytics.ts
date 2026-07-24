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

export const todayIso = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

/** Inclusive local calendar day N days before today (0 = today). */
export const daysAgoIso = (days: number) => {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  local.setUTCDate(local.getUTCDate() - Math.max(0, Math.floor(days)));
  return local.toISOString().slice(0, 10);
};

/** Default Reports range: today (Nairobi/local calendar day). */
export const defaultAnalyticsRange = () => {
  const day = todayIso();
  return { start: day, end: day };
};

export function formatMoney(value: unknown, currency = "KES") {
  const amount = Number(value || 0);
  return `${currency} ${Number.isFinite(amount) ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0.00"}`;
}

/** KPI-safe currency: never mid-number ellipsis; abbreviate large values. */
export function formatCompactMoney(value: unknown, currency = "KES") {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount)) return `${currency} 0`;
  const sign = amount < 0 ? "-" : "";
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) {
    const digits = abs >= 10_000_000 ? 0 : 1;
    return `${currency} ${sign}${(abs / 1_000_000).toFixed(digits)}M`;
  }
  if (abs >= 10_000) {
    return `${currency} ${sign}${(abs / 1_000).toFixed(1)}K`;
  }
  if (Math.abs(abs - Math.round(abs)) < 0.005) {
    return `${currency} ${sign}${Math.round(abs).toLocaleString()}`;
  }
  return `${currency} ${sign}${abs.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatNumber(value: unknown, digits = 0) {
  const amount = Number(value || 0);
  return Number.isFinite(amount)
    ? amount.toLocaleString(undefined, { maximumFractionDigits: digits })
    : "0";
}

export function formatDateTime(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
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
