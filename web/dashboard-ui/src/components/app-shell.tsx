import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import {
  LayoutDashboard,
  ShoppingCart,
  Package,
  Banknote,
  BarChart3,
  NotebookPen,
  Users,
  Settings,
  ShieldCheck,
  KeyRound,
  Wrench,
  Moon,
  Sun,
  RefreshCw,
  LogOut,
  Circle,
  Menu,
  X,
  Bell,
  Activity,
  ClipboardCheck,
  HeartPulse,
  HardDrive,
  GitBranch,
  Sparkles,
  MoreHorizontal,
  Search,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "./theme";
import { useAuth } from "@/lib/auth";
import { GET } from "@/lib/api";
import { KES } from "@/lib/format";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  super?: boolean;
  group?: string;
};

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, group: "Overview" },
  { to: "/live", label: "Live", icon: Activity, group: "Overview" },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck, group: "Overview" },
  { to: "/pos", label: "Point of Sale", icon: ShoppingCart, group: "Operations" },
  { to: "/inventory", label: "Inventory", icon: Package, group: "Operations" },
  { to: "/debt", label: "Debt Management", icon: Banknote, group: "Operations" },
  { to: "/reports", label: "Reports", icon: BarChart3, group: "Operations" },
  { to: "/notifications", label: "Notifications", icon: Bell, group: "Command" },
  { to: "/health", label: "System Health", icon: HeartPulse, group: "Command" },
  { to: "/backup", label: "Backup", icon: HardDrive, group: "Command" },
  { to: "/branches", label: "Branches", icon: GitBranch, group: "Command" },
  { to: "/ai", label: "AI Center", icon: Sparkles, group: "Command" },
  { to: "/notes", label: "Notes", icon: NotebookPen, group: "Admin" },
  { to: "/users", label: "Users & Access", icon: Users, group: "Admin" },
  { to: "/settings", label: "Settings", icon: Settings, group: "Admin" },
  { to: "/security", label: "Security", icon: ShieldCheck, super: true, group: "Admin" },
  { to: "/license", label: "License", icon: KeyRound, super: true, group: "Admin" },
  { to: "/diagnostics", label: "Diagnostics", icon: Wrench, group: "Admin" },
];

const MOBILE_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/live", label: "Live", icon: Activity },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { to: "/inventory", label: "Inventory", icon: Package },
] as const;

function useClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const i = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(i);
  }, []);
  return now;
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, toggle } = useTheme();
  const Icon = theme === "dark" ? Sun : Moon;
  const label = theme === "dark" ? "Light" : "Dark";
  return (
    <button
      onClick={toggle}
      className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-text hover:bg-hover transition-ui min-h-[44px] sm:min-h-0"
      aria-label="Toggle theme"
    >
      <Icon className="h-4 w-4 text-gold" />
      {!compact && <span className="hidden sm:inline">{label}</span>}
    </button>
  );
}

function SidebarContent({
  onNavigate,
  showTodaySummary = false,
  todaySales = 0,
  todayOrders = 0,
  todayProfit = 0,
  versionLabel,
}: {
  onNavigate?: () => void;
  showTodaySummary?: boolean;
  todaySales?: number;
  todayOrders?: number;
  todayProfit?: number;
  versionLabel?: string;
}) {
  const location = useLocation();
  const { user, logout } = useAuth();
  const displayName = user?.full_name || user?.username || "Staff";
  const role = String(user?.role || "cashier").toUpperCase();
  const groups = ["Overview", "Operations", "Command", "Admin"] as const;

  return (
    <>
      <div className="px-4 py-5 border-b border-border flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-gold text-sm font-black text-[color:var(--gold-fg)] shadow-gold">
          MBT
        </div>
        <div className="leading-tight min-w-0">
          <div className="font-display font-extrabold text-gold text-lg tracking-wide">MBT POS</div>
          <div className="text-eyebrow text-text2">SYSTEM</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin py-3 px-2.5">
        {groups.map((group) => {
          const items = NAV.filter((n) => n.group === group);
          if (!items.length) return null;
          return (
            <div key={group} className="mb-3">
              <div className="px-3 pt-1.5 pb-1.5 text-eyebrow text-muted-fg">{group}</div>
              <div className="space-y-0.5">
                {items.map((item) => {
                  const active =
                    item.to === "/"
                      ? location.pathname === "/"
                      : location.pathname.startsWith(item.to);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      onClick={onNavigate}
                      className={cn(
                        "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-ui min-h-[40px]",
                        active
                          ? showTodaySummary
                            ? "bg-info/15 text-info font-semibold shadow-sm"
                            : "bg-hover text-gold font-semibold shadow-sm"
                          : "text-text2 hover:text-text hover:bg-hover/50",
                      )}
                    >
                      <span
                        className={cn(
                          "absolute left-0 top-2 bottom-2 w-[3px] rounded-r transition-ui",
                          active
                            ? showTodaySummary
                              ? "bg-info"
                              : "bg-gold"
                            : "bg-transparent group-hover:bg-border2",
                        )}
                      />
                      <Icon
                        className={cn(
                          "h-4 w-4 shrink-0",
                          active && (showTodaySummary ? "text-info" : "text-gold"),
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {showTodaySummary ? (
        <div className="mx-2.5 mb-2 rounded-xl border border-border bg-card/80 p-3 space-y-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-fg">
            Today&apos;s Summary
          </div>
          <div className="flex justify-between text-[12px]">
            <span className="text-text2">Sales</span>
            <span className="font-semibold text-text tabular-nums">{KES(todaySales)}</span>
          </div>
          <div className="flex justify-between text-[12px]">
            <span className="text-text2">Orders</span>
            <span className="font-semibold text-text tabular-nums">{todayOrders}</span>
          </div>
          <div className="flex justify-between text-[12px]">
            <span className="text-text2">Profit</span>
            <span className="font-semibold text-ok tabular-nums">{KES(todayProfit)}</span>
          </div>
        </div>
      ) : null}

      <div className="px-3 py-3.5 border-t border-border bg-panel/50">
        {versionLabel ? (
          <div className="text-[10px] font-mono text-muted-fg mb-2">{versionLabel}</div>
        ) : null}
        <div className="text-sm font-semibold text-text truncate">{displayName}</div>
        <div className="text-eyebrow text-gold mb-2.5 mt-0.5">{role}</div>
        <button
          type="button"
          onClick={() => logout()}
          className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-text hover:bg-hover hover:border-err/40 hover:text-err transition-ui min-h-[44px]"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign Out
        </button>
      </div>
    </>
  );
}

function HwDot({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Circle className="h-2 w-2 fill-ok text-ok" />
      <span>
        {label}: <span className="text-ok">Connected</span>
      </span>
    </span>
  );
}

function OnlineBadge() {
  const healthQ = useQuery({
    queryKey: ["health-ping"],
    queryFn: async () => {
      const t0 = performance.now();
      const r = await fetch("/api/health");
      const ms = Math.round(performance.now() - t0);
      const data = await r.json().catch(() => ({}));
      return { ok: r.ok && (data as any)?.status === "ok", ms };
    },
    refetchInterval: 30_000,
    retry: 1,
  });
  const online = healthQ.data?.ok !== false && !healthQ.isError;
  return (
    <div
      className={cn(
        "hidden sm:inline-flex items-center gap-1.5 font-medium text-xs px-2 py-1 rounded-md border",
        online ? "text-ok border-ok/25 bg-ok/10" : "text-err border-err/25 bg-err/10",
      )}
      title={online ? `API ~${healthQ.data?.ms ?? "—"} ms` : "API unreachable"}
    >
      <Circle className={cn("h-2 w-2 fill-current", online && "animate-pulse")} />
      {online ? "Online" : "Offline"}
    </div>
  );
}

function GlobalSearch({ wide = false }: { wide?: boolean }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const searchQ = useQuery({
    queryKey: ["global-search", q],
    queryFn: () =>
      GET<{ results: any[] }>("/search", { q }),
    enabled: q.trim().length >= 2,
  });
  const results = searchQ.data?.results || [];

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) {
        if (e.key === "Escape") {
          setOpen(false);
          (e.target as HTMLElement).blur();
        }
        return;
      }
      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setOpen(true);
        inputRef.current?.focus();
      }
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(true);
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      ref={wrapRef}
      className={cn(
        "relative hidden md:block",
        wide ? "w-[280px] lg:w-[380px]" : "w-[220px] lg:w-[280px]",
      )}
    >
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text2 pointer-events-none" />
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          if (wide) {
            window.dispatchEvent(
              new CustomEvent("mbt-pos-query", { detail: e.target.value }),
            );
          }
        }}
        onFocus={() => setOpen(true)}
        placeholder={wide ? "Search products by name, barcode or SKU…" : "Search…  /"}
        className="h-9 w-full rounded-lg bg-input border border-border pl-8 pr-14 text-sm text-text placeholder:text-muted-fg focus:outline-none focus:border-gold/60 focus:ring-2 focus:ring-gold/25"
      />
      <kbd className="absolute right-2 top-1/2 -translate-y-1/2 hidden lg:inline-flex items-center rounded border border-border bg-card2 px-1.5 py-0.5 text-[10px] font-mono text-muted-fg">
        Ctrl K
      </kbd>
      {open && q.trim().length >= 2 && !wide ? (
        <div className="absolute top-full left-0 right-0 mt-1.5 z-50 rounded-lg border border-border bg-card shadow-lg max-h-[360px] overflow-y-auto">
          {searchQ.isFetching ? (
            <div className="px-3 py-3 text-xs text-text2">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-3 py-3 text-xs text-text2">No matches</div>
          ) : (
            <ul className="py-1">
              {results.map((r: any) => (
                <li key={`${r.type}-${r.id}`}>
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2.5 hover:bg-hover transition-ui"
                    onClick={() => {
                      setOpen(false);
                      setQ("");
                      navigate({ to: r.href || "/" });
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-text truncate">{r.title}</span>
                      <span className="text-[10px] uppercase tracking-wide text-muted-fg shrink-0">
                        {r.type}
                      </span>
                    </div>
                    <div className="text-xs text-text2 truncate">
                      {r.subtitle}
                      {r.meta != null && r.type !== "user" ? ` · ${KES(r.meta)}` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function AppShell({
  title,
  children,
  density = "default",
}: {
  title: string;
  children: ReactNode;
  /** POS floor uses full-bleed panels + hardware strip */
  density?: "default" | "pos";
}) {
  const now = useClock();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isPos = density === "pos";

  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<{ version?: string; build?: string; exe?: string }>("/version"),
    staleTime: 60_000 * 10,
  });
  const notifQ = useQuery({
    queryKey: ["notifications-badge"],
    queryFn: () => GET<{ unread?: number }>("/notifications", { limit: "1" }),
    refetchInterval: 45_000,
  });
  const todayQ = useQuery({
    queryKey: ["sales-today"],
    queryFn: () => {
      const d = new Date().toISOString().slice(0, 10);
      return GET<{
        sales_total?: number;
        orders?: number;
        profit?: number;
        total?: number;
        count?: number;
        revenue?: number;
      }>("/reports/summary", { start: d, end: d });
    },
    enabled: isPos,
    refetchInterval: 60_000,
    retry: 0,
  });
  const unread = Number(notifQ.data?.unread || 0);
  const ver = versionQ.data?.version || "2.3.92";
  const build = versionQ.data?.build || "PROD-2026-07-19-v2.3.92";
  const exe = versionQ.data?.exe || "MBT_POS.exe";
  const displayName = user?.full_name || user?.username || "Staff";
  const initials = displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("") || "MB";
  const todaySales = Number(
    todayQ.data?.sales_total ?? todayQ.data?.total ?? todayQ.data?.revenue ?? 0,
  );
  const todayOrders = Number(todayQ.data?.orders ?? todayQ.data?.count ?? 0);
  const todayProfit = Number(todayQ.data?.profit ?? 0);

  const dateStr = now
    ? now.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" })
    : "";
  const timeStr = now ? now.toLocaleTimeString("en-GB", { hour12: false }) : "--:--:--";

  const refresh = useCallback(() => {
    qc.invalidateQueries();
  }, [qc]);

  useEffect(() => {
    let pendingG = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) {
        return;
      }
      if (e.key === "g" || e.key === "G") {
        pendingG = true;
        clearTimeout(timer);
        timer = setTimeout(() => {
          pendingG = false;
        }, 800);
        return;
      }
      if (pendingG && (e.key === "d" || e.key === "D")) {
        pendingG = false;
        navigate({ to: "/" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
    };
  }, [navigate]);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-screen flex flex-col bg-app text-text">
      <div className="flex flex-1 min-h-0">
        {/* Desktop Sidebar */}
        <aside className="hidden lg:flex w-[240px] shrink-0 flex-col bg-sidebar border-r border-border">
          <SidebarContent
            showTodaySummary={isPos}
            todaySales={todaySales}
            todayOrders={todayOrders}
            todayProfit={todayProfit}
            versionLabel={`MBT POS v${ver}`}
          />
        </aside>

        {/* Mobile drawer */}
        {mobileOpen && (
          <div className="lg:hidden fixed inset-0 z-50 flex">
            <div
              className="absolute inset-0 bg-black/65 backdrop-blur-[2px] transition-ui"
              onClick={() => setMobileOpen(false)}
            />
            <aside className="relative w-[300px] max-w-[88vw] flex flex-col bg-sidebar border-r border-border shadow-lg animate-in slide-in-from-left duration-200">
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-2 top-2 z-10 inline-flex items-center justify-center h-11 w-11 rounded-lg text-text2 hover:bg-hover transition-ui"
                aria-label="Close menu"
              >
                <X className="h-4 w-4" />
              </button>
              <SidebarContent
                onNavigate={() => setMobileOpen(false)}
                showTodaySummary={isPos}
                todaySales={todaySales}
                todayOrders={todayOrders}
                todayProfit={todayProfit}
                versionLabel={`MBT POS v${ver}`}
              />
            </aside>
          </div>
        )}

        {/* Main */}
        <div className="flex-1 min-w-0 flex flex-col bg-surface">
          <header className="h-14 shrink-0 flex items-center justify-between gap-2 sm:gap-4 px-3 sm:px-5 border-b border-border bg-panel/70 backdrop-blur-sm sticky top-0 z-20">
            <div className="flex items-center gap-2.5 min-w-0">
              <button
                onClick={() => setMobileOpen(true)}
                className="lg:hidden inline-flex items-center justify-center h-11 w-11 rounded-lg border border-border bg-card text-text hover:bg-hover transition-ui"
                aria-label="Open menu"
              >
                <Menu className="h-4 w-4" />
              </button>
              <div className="min-w-0">
                <h1 className="text-[15px] font-semibold text-text truncate tracking-tight">{title}</h1>
              </div>
            </div>
            <div className="flex items-center gap-1.5 sm:gap-2.5 text-sm">
              <GlobalSearch wide={isPos} />
              <OnlineBadge />
              {isPos ? (
                <div className="hidden md:inline-flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5">
                  <div className="h-7 w-7 rounded-full bg-info/20 text-info text-[10px] font-bold grid place-items-center">
                    {initials}
                  </div>
                  <span className="text-xs font-medium text-text max-w-[100px] truncate">
                    {displayName}
                  </span>
                </div>
              ) : null}
              <Link
                to="/notifications"
                className="relative inline-flex items-center justify-center h-11 w-11 sm:h-9 sm:w-9 rounded-lg border border-border bg-card text-text hover:bg-hover transition-ui"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
                {unread > 0 ? (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-err text-[10px] font-bold text-white grid place-items-center shadow-sm">
                    {unread > 9 ? "9+" : unread}
                  </span>
                ) : null}
              </Link>
              <button
                type="button"
                onClick={refresh}
                className="hidden md:inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 hover:bg-hover text-text transition-ui"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
              <ThemeToggle />
              <div className="hidden md:block text-text2 tabular-nums text-xs pl-2.5 border-l border-border">
                <span className="mr-3">{dateStr}</span>
                <span className="font-mono text-text">{timeStr}</span>
              </div>
            </div>
          </header>

          <main
            className={cn(
              "flex-1 min-h-0 overflow-y-auto scrollbar-thin overflow-x-hidden",
              isPos ? "pb-[52px] lg:pb-9" : "pb-[76px] lg:pb-0",
            )}
          >
            <div
              key={location.pathname}
              className={cn(
                "page-enter",
                isPos ? "p-2.5 sm:p-3 max-w-none" : "p-3 sm:p-6 max-w-[1400px]",
              )}
            >
              {children}
            </div>
          </main>

          {isPos ? (
            <footer className="hidden lg:flex min-h-9 shrink-0 items-center justify-between gap-3 px-4 py-1.5 border-t border-border bg-panel/80 text-[11px] text-text2">
              <div className="flex items-center gap-4">
                <HwDot label="Barcode Scanner" />
                <HwDot label="Receipt Printer" />
                <HwDot label="Cash Drawer" />
              </div>
              <span className="font-mono truncate">
                Last Sync: just now · v{ver}
              </span>
            </footer>
          ) : (
            <footer className="hidden lg:flex min-h-9 shrink-0 items-center justify-between gap-1 px-3 sm:px-6 py-1.5 border-t border-border bg-panel/60 text-[11px] text-text2">
              <span>MBT POS · MugoByte Technologies</span>
              <span className="font-mono truncate" title="Press / to search · g then d for dashboard">
                v{ver} · {build} · EXE:{exe}
              </span>
            </footer>
          )}
        </div>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-panel/95 backdrop-blur-md safe-bottom shadow-[0_-8px_24px_-12px_rgba(0,0,0,0.4)]">
        <div className="grid grid-cols-5">
          {MOBILE_NAV.map((item) => {
            const active =
              item.to === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "relative flex flex-col items-center justify-center gap-0.5 min-h-[60px] text-[10px] font-semibold transition-ui",
                  active ? "text-gold" : "text-text2",
                )}
              >
                {active ? (
                  <span className="absolute top-0 inset-x-4 h-0.5 rounded-b bg-gold" />
                ) : null}
                <span
                  className={cn(
                    "inline-flex items-center justify-center h-8 w-8 rounded-xl transition-ui",
                    active && "bg-gold/15",
                  )}
                >
                  <Icon className={cn("h-5 w-5", active && "text-gold")} />
                </span>
                {item.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex flex-col items-center justify-center gap-0.5 min-h-[60px] text-[10px] font-semibold text-text2 transition-ui"
          >
            <span className="inline-flex items-center justify-center h-8 w-8 rounded-xl">
              <MoreHorizontal className="h-5 w-5" />
            </span>
            More
          </button>
        </div>
      </nav>
    </div>
  );
}
