import { useState } from "react";
import { addDays, endOfMonth, format, startOfMonth, subDays } from "date-fns";
import type { DateRange } from "react-day-picker";
import { CalendarDays, ChevronLeft, ChevronRight, Download, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const iso = (date: Date) => format(date, "yyyy-MM-dd");

export function DateRangePicker({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = { from: new Date(`${start}T00:00:00`), to: new Date(`${end}T00:00:00`) };
  const apply = (from: Date, to = from) => {
    onChange(iso(from), iso(to));
    setOpen(false);
  };
  const presets = [
    ["Today", new Date(), new Date()],
    ["Yesterday", subDays(new Date(), 1), subDays(new Date(), 1)],
    ["Last 7 Days", subDays(new Date(), 6), new Date()],
    ["Last 30 Days", subDays(new Date(), 29), new Date()],
    ["This Month", startOfMonth(new Date()), endOfMonth(new Date())],
  ] as const;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="min-w-56 justify-start font-normal">
          <CalendarDays className="mr-2 h-4 w-4" />
          {start === end
            ? format(selected.from, "MMM d, yyyy")
            : `${format(selected.from, "MMM d, yyyy")} – ${format(selected.to, "MMM d, yyyy")}`}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-auto p-0">
        <div className="flex flex-wrap gap-1 border-b p-2">
          {presets.map(([label, from, to]) => (
            <Button key={label} size="sm" variant="ghost" onClick={() => apply(from, to)}>
              {label}
            </Button>
          ))}
        </div>
        <Calendar
          mode="range"
          selected={selected}
          numberOfMonths={typeof window !== "undefined" && window.innerWidth < 768 ? 1 : 2}
          disabled={{ after: addDays(new Date(), 0) }}
          onSelect={(range: DateRange | undefined) => {
            if (!range?.from) return;
            if (range.to) apply(range.from, range.to);
            else onChange(iso(range.from), iso(range.from));
          }}
          className="max-md:[--cell-size:1.75rem]"
        />
      </PopoverContent>
    </Popover>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder = "Search…",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="relative min-w-52 flex-1 sm:max-w-xs">
      <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="pl-9" />
    </div>
  );
}

export function FilterSelect({
  value,
  onChange,
  label,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <Select value={value || "all"} onValueChange={(next) => onChange(next === "all" ? "" : next)}>
      <SelectTrigger className="w-full sm:w-44"><SelectValue placeholder={label} /></SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All {label.toLowerCase()}</SelectItem>
        {options.filter((option) => option.value).map((option) => (
          <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function ExportButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <Button variant="outline" onClick={onClick} disabled={loading}>
      {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
      Export all
    </Button>
  );
}

export function ReportPagination({
  page,
  pages,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  if (!total) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <div className="flex flex-col gap-3 border-t px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <span className="text-muted-foreground">Showing {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="h-4 w-4" /> Previous
        </Button>
        <span className="min-w-24 text-center">Page {page} of {pages}</span>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function Segmented({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <div className="inline-flex rounded-lg bg-muted p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn("rounded-md px-3 py-1.5 text-sm font-medium transition", value === option.value ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
