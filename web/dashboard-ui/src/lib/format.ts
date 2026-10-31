/** Currency / display helpers shared across dashboard pages */

export function KES(n: number, symbol = "KES") {
  const v = Number(n) || 0;
  return `${symbol} ${v.toLocaleString("en-KE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}`;
}

export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

/** Shop-local calendar day. UTC ISO is the previous day in the evening in Kenya. */
export function localISO(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Africa/Nairobi calendar day, matching the till. */
export function shopTodayISO(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function saleDayCaption(iso: string, today = shopTodayISO()) {
  if (!iso || iso === today) return { text: "Today", tone: "today" as const };
  const [year, month, day] = iso.split("-").map(Number);
  const label = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(Date.UTC(year, (month || 1) - 1, day || 1)));
  if (iso < today) return { text: `${label} — BACKDATED`, tone: "backdated" as const };
  return { text: `${label} — FUTURE DATE`, tone: "future" as const };
}

export function rangeForPreset(preset: string): { start: string; end: string } {
  const now = new Date();
  const end = localISO(now);
  if (preset === "Yesterday" || preset === "yesterday") {
    const y = new Date(now);
    y.setDate(y.getDate() - 1);
    const day = localISO(y);
    return { start: day, end: day };
  }
  if (preset === "This Week" || preset === "week") {
    const start = new Date(now);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    const finish = new Date(start);
    finish.setDate(start.getDate() + 6);
    return { start: localISO(start), end: localISO(finish) };
  }
  if (preset === "This Month" || preset === "month") {
    const start = new Date(now.getFullYear(), now.getMonth(), 1);
    const finish = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    return { start: localISO(start), end: localISO(finish) };
  }
  if (preset === "Last Month" || preset === "last_month") {
    const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const finish = new Date(now.getFullYear(), now.getMonth(), 0);
    return { start: localISO(start), end: localISO(finish) };
  }
  if (preset === "Last Week" || preset === "last_week") {
    const start = new Date(now);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 7);
    const finish = new Date(start);
    finish.setDate(start.getDate() + 6);
    return { start: localISO(start), end: localISO(finish) };
  }
  if (preset === "This Year" || preset === "year") {
    const start = new Date(now.getFullYear(), 0, 1);
    const finish = new Date(now.getFullYear(), 11, 31);
    return { start: localISO(start), end: localISO(finish) };
  }
  return { start: end, end };
}

export function addDaysISO(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}
