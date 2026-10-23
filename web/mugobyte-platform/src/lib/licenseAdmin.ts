/** Rules for the portal admin licence page. POS and Pulse share one device id format. */

export const LICENSE_PRODUCTS = [
  { id: "mbt-pos", name: "MBT POS" },
  { id: "pulse", name: "Pulse" },
] as const;

/** POS phones home within 7 days. Pulse uses a 30-day window. */
export function graceDaysFor(productId?: string | null): number {
  return (productId || "mbt-pos").toLowerCase() === "pulse" ? 30 : 7;
}

export const OFFLINE_GRACE_DAYS = 30;

export function deviceIdError(deviceId: string): string | null {
  const id = deviceId.trim();
  if (!id) return "Enter the device id";
  if (/^MBT-PC-[A-Z0-9]+$/i.test(id)) return null;
  if (/^[a-f0-9]{32,64}$/i.test(id)) return null;
  return "Use MBT-PC-XXXX or the device id shown in the app";
}

export function normalizeDeviceId(deviceId: string): string {
  const id = deviceId.trim();
  return /^MBT-PC-/i.test(id) ? id.toUpperCase() : id.toLowerCase();
}

export type GraceView = "Not seen yet" | "Within grace" | "Grace lock";

export function graceView(
  lastSeenAt: string | null | undefined,
  nowMs = Date.now(),
  graceDays = OFFLINE_GRACE_DAYS,
): GraceView {
  if (!lastSeenAt) return "Not seen yet";
  const at = Date.parse(lastSeenAt);
  if (!Number.isFinite(at)) return "Not seen yet";
  const elapsedDays = (nowMs - at) / 86_400_000;
  return elapsedDays > graceDays ? "Grace lock" : "Within grace";
}

export function cleanDeviceId(deviceId: string): string {
  const id = deviceId.trim();
  if (!id) return "";
  const error = deviceIdError(id);
  if (error) throw new Error(error);
  return normalizeDeviceId(id);
}
