import { useMemo, useState } from "react";
import { Button } from "@/components/ui-kit";
import { shopTodayISO } from "@/lib/format";

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function toISO(day: Date) {
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

function fromISO(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function label(value: string) {
  return fromISO(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function shiftMonth(cursor: Date, delta: number) {
  return new Date(cursor.getFullYear(), cursor.getMonth() + delta, 1);
}

function addDays(iso: string, delta: number) {
  const [year, month, day] = iso.split("-").map(Number);
  return toISO(new Date(year, (month || 1) - 1, (day || 1) + delta));
}

export function DateRangeField({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}) {
  const today = shopTodayISO();
  const [open, setOpen] = useState(false);
  const [draftStart, setDraftStart] = useState(start);
  const [draftEnd, setDraftEnd] = useState(end);
  const [awaitingEnd, setAwaitingEnd] = useState(false);
  const [cursor, setCursor] = useState(() => fromISO(start));

  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const days = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
    const blanks = (first.getDay() + 6) % 7;
    return { blanks, days, month: first.toLocaleDateString("en-GB", { month: "long", year: "numeric" }) };
  }, [cursor]);

  function openPicker() {
    setDraftStart(start);
    setDraftEnd(end);
    setAwaitingEnd(false);
    setCursor(fromISO(end || start));
    setOpen(true);
  }

  function choose(iso: string) {
    if (iso > today) return;
    if (!awaitingEnd) {
      setDraftStart(iso);
      setDraftEnd(iso);
      setAwaitingEnd(true);
      return;
    }
    const [from, to] = iso < draftStart ? [iso, draftStart] : [draftStart, iso];
    setDraftStart(from);
    setDraftEnd(to);
    setAwaitingEnd(false);
  }

  function applyPreset(from: string, to: string) {
    onChange(from, to);
    setOpen(false);
  }

  function applyDraft() {
    const [from, to] = draftEnd < draftStart ? [draftEnd, draftStart] : [draftStart, draftEnd];
    onChange(from, to);
    setOpen(false);
  }

  const yesterday = addDays(today, -1);
  const week = addDays(today, -6);
  const monthStart = `${today.slice(0, 8)}01`;

  return (
    <div className="relative md:col-span-2">
      <button
        type="button"
        aria-label="Date range"
        onClick={() => (open ? setOpen(false) : openPicker())}
        className="flex h-9 w-full items-center rounded-lg border border-border bg-input px-3 text-left text-sm font-medium text-text hover:border-gold"
      >
        Calendar &nbsp; {label(start)} – {label(end)}
      </button>
      {open ? (
        <div className="absolute left-0 z-30 mt-2 w-[340px] rounded-xl border border-border bg-card p-3 shadow-card">
          <p className="mb-2 text-xs text-text2">
            {awaitingEnd ? "Now click the last day." : "Click the first day, then the last day."}
          </p>
          <div className="mb-2 flex flex-wrap gap-1">
            <Button size="sm" variant="ghost" onClick={() => applyPreset(today, today)}>Today</Button>
            <Button size="sm" variant="ghost" onClick={() => applyPreset(yesterday, yesterday)}>Yesterday</Button>
            <Button size="sm" variant="ghost" onClick={() => applyPreset(week, today)}>Last 7 days</Button>
            <Button size="sm" variant="ghost" onClick={() => applyPreset(monthStart, today)}>This month</Button>
          </div>
          <div className="mb-2 flex items-center justify-between">
            <Button size="sm" variant="ghost" onClick={() => setCursor((current) => shiftMonth(current, -1))} aria-label="Previous month">‹</Button>
            <span className="text-sm font-semibold text-text">{cells.month}</span>
            <Button size="sm" variant="ghost" onClick={() => setCursor((current) => shiftMonth(current, 1))} aria-label="Next month">›</Button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-text2">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((name) => <span key={name}>{name}</span>)}
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1">
            {Array.from({ length: cells.blanks }, (_, index) => <span key={`b${index}`} />)}
            {Array.from({ length: cells.days }, (_, index) => {
              const iso = toISO(new Date(cursor.getFullYear(), cursor.getMonth(), index + 1));
              const selected = iso === draftStart || iso === draftEnd;
              const between = iso > draftStart && iso < draftEnd;
              const future = iso > today;
              return (
                <button
                  key={iso}
                  type="button"
                  disabled={future}
                  onClick={() => choose(iso)}
                  className={`h-9 rounded-md text-sm font-semibold ${
                    selected ? "bg-gold text-black" : between ? "bg-gold/20 text-text" : "text-text hover:bg-hover"
                  } disabled:text-text2/40`}
                >
                  {index + 1}
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-sm font-semibold text-gold">{label(draftStart)} – {label(draftEnd)}</p>
          <div className="mt-2 flex gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={applyDraft}>Use these dates</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
