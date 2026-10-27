/** Shop-wide mouse-wheel steps. Typing a decimal is still allowed. */

export const WHEEL_DEFAULTS = {
  wheel_pos_qty: "0.25",
  wheel_stock_adjust: "1",
  wheel_receive_qty: "1",
  wheel_dashboard_qty: "1",
} as const;

export type WheelKey = keyof typeof WHEEL_DEFAULTS;

export function wheelStep(settings: Record<string, string> | undefined, key: WheelKey): number {
  const raw = settings?.[key] ?? WHEEL_DEFAULTS[key];
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0 || n > 1000) return Number(WHEEL_DEFAULTS[key]);
  return Math.round(n * 1000) / 1000;
}

export function roundMoneyQty(value: number): number {
  const n = Math.round(Number(value) * 100) / 100;
  if (!Number.isFinite(n) || n <= 0) return 0;
  return n;
}
