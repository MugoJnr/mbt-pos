import { getUser } from "@/lib/api";
import { shopTodayISO } from "@/lib/format";

export function canPostBusinessDay() {
  const user = getUser();
  const actions = user?.effective_permissions;
  if (Array.isArray(actions)) return actions.map(String).includes("sales.business_day");
  const role = String(user?.role || "").toLowerCase();
  return role === "manager" || role === "admin" || role === "superadmin";
}

export function backdateWarning(iso: string) {
  const [year, month, day] = String(iso || "").split("-").map(Number);
  const when = Number.isFinite(year)
    ? new Date(Date.UTC(year, (month || 1) - 1, day || 1)).toLocaleDateString("en-GB", {
        timeZone: "UTC",
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : iso;
  return `You're recording this transaction for ${when}, not today's date. This is a backdated transaction and requires administrator approval before it is posted.`;
}

export const BACKDATE_REASONS = [
  "Network or system downtime",
  "Transaction entered late",
  "Previous transaction was missed",
  "Supplier delivery recorded late",
  "Correction of an earlier recording error",
  "Supporting documents received late",
  "Other",
];

export function BusinessDateField({
  value,
  onChange,
  label = "Business date",
  confirmed = false,
  onConfirm,
  reason = "",
  onReason,
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  confirmed?: boolean;
  onConfirm?: (value: boolean) => void;
  reason?: string;
  onReason?: (value: string) => void;
}) {
  const today = shopTodayISO();
  const past = Boolean(value) && value < today;
  const direct = canPostBusinessDay();
  return (
    <div className="block text-xs font-semibold text-text2">
      <span>{label}</span>
      <input
        aria-label={label}
        type="date"
        max={today}
        value={value || today}
        onChange={(event) => {
          onChange(event.target.value || today);
          onConfirm?.(false);
        }}
        className="mt-1 h-11 w-full rounded-lg border border-border bg-input px-3 text-sm text-text"
      />
      {past && !direct ? (
        <span className="mt-2 block rounded-lg border border-err/40 bg-err/10 p-2 text-sm font-medium text-err">
          {backdateWarning(value)}
          {onConfirm ? (
            <label className="mt-2 flex items-start gap-2 text-text">
              <input
                aria-label="Confirm backdated transaction"
                type="checkbox"
                checked={confirmed}
                onChange={(event) => onConfirm(event.target.checked)}
              />
              <span>I understand this stays pending until a different administrator approves it.</span>
            </label>
          ) : null}
        </span>
      ) : null}
      {past && direct ? (
        <span className="mt-2 block text-sm text-text2">
          This will be posted on {value}, which is not today.
        </span>
      ) : null}
      {past && onReason ? (
        <div className="mt-2 block text-text">
          <span>Why this past date</span>
          <select
            aria-label="Backdating reason"
            value={BACKDATE_REASONS.includes(reason) ? reason : reason ? "Other" : ""}
            onChange={(event) => onReason(event.target.value)}
            className="mt-1 h-11 w-full rounded-lg border border-border bg-input px-3 text-sm text-text"
          >
            <option value="">Choose a reason</option>
            {BACKDATE_REASONS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
          {reason === "Other" || (reason && !BACKDATE_REASONS.includes(reason)) ? (
            <input
              aria-label="Backdating explanation"
              value={reason === "Other" ? "" : BACKDATE_REASONS.includes(reason) ? "" : reason.replace(/^Other:\s*/, "")}
              placeholder="What happened"
              onChange={(event) => onReason(event.target.value.trim() ? `Other: ${event.target.value.trim()}` : "Other")}
              className="mt-2 h-11 w-full rounded-lg border border-border bg-input px-3 text-sm text-text"
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
