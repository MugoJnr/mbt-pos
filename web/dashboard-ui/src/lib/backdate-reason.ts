export const BACKDATE_REASONS = [
  "Network or system downtime",
  "Transaction entered late",
  "Previous transaction was missed",
  "Supplier delivery recorded late",
  "Correction of an earlier recording error",
  "Supporting documents received late",
  "Other",
];

export function catalogReasonValue(reason: string) {
  const text = reason || "";
  if (!text) return "";
  return BACKDATE_REASONS.includes(text) ? text : "Other";
}

/** Keep spaces the cashier is still typing. Trim only when the reason is saved. */
export function otherReasonDraft(reason: string) {
  if (reason.startsWith("Other: ")) return reason.slice(7);
  if (reason.startsWith("Other:")) return reason.slice(6);
  if (reason && reason !== "Other" && !BACKDATE_REASONS.includes(reason)) return reason;
  return "";
}

export function reasonFromOtherDraft(draft: string) {
  return draft.length ? `Other: ${draft}` : "Other";
}

export function normalizeBackdateReason(reason: string) {
  const text = (reason || "").trim();
  if (!text.startsWith("Other:")) return text;
  const detail = text.slice(6).trim();
  return detail ? `Other: ${detail}` : "Other";
}

export function showsOtherReasonField(reason: string) {
  return catalogReasonValue(reason) === "Other" && Boolean(reason);
}
