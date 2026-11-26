const NAIROBI_LABEL = "Nairobi / East Africa Time";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function wallClock(raw: string): string | null {
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!match) return null;
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) return null;
  return `${Number(match[3])} ${month} ${match[1]}, ${match[4]}:${match[5]} ${NAIROBI_LABEL}`;
}

/** Show a licence instant in East Africa Time without moving a Nairobi clock twice. */
export function formatLicenceTime(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "—";
  const zone = raw.match(/([+-]\d{2}:?\d{2}|Z)$/i);
  const offset = zone ? zone[1].toUpperCase() : "";
  if (!offset || offset === "+03:00" || offset === "+0300") {
    const wall = wallClock(raw);
    if (wall) return wall;
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw.replace(/\bUTC\b/g, NAIROBI_LABEL);
  }
  const text = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Nairobi",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return `${text} ${NAIROBI_LABEL}`;
}
