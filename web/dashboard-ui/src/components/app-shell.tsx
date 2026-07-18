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
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "./theme";
import { useAuth } from "@/lib/auth";
import { GET } from "@/lib/api";

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
      className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-text hover:bg-hover transition-colors min-h-[44px] sm:min-h-0"
      aria-label="Toggle theme"
    >
      <Icon className="h-4 w-4 text-gold" />
      {!compact && <span className="hidden sm:inline">{label}</span>}
    </button>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  const { user, logout } = useAuth();
  const displayName = user?.full_name || user?.username || "Staff";
  const role = String(user?.role || "cashier").toUpperCase();
  const groups = ["Overview", "Operations", "Command", "Admin"] as const;

  return (
    <>
      <div className="px-4 py-5 border-b border-border flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-gold text-sm font-black text-[color:var(--gold-fg)] shadow-[0_2px_8px_rgba(242,168,0,0.35)]">
          MBT
        </div>
        <div className="leading-tight">
          <div className="font-display font-extrabold text-gold text-lg tracking-wide">MBT</div>
          <div className="text-[10px] tracking-[0.18em] text-text2 font-semibold">
            COMMAND CENTER
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin py-2 px-2">
        {groups.map((group) => {
          const items = NAV.filter((n) => n.group === group);
          if (!items.length) return null;
          return (
            <div key={group} className="mb-2">
              <div className="px-3 pt-2 pb-1 text-[9px] tracking-[0.2em] font-semibold text-muted-fg uppercase">
                {group}
              </div>
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
                    className={`group relative flex items-center gap-3 rounded-md px-3 py-2.5 my-0.5 text-sm transition-colors ${
                      active
                        ? "bg-hover text-gold font-semibold"
                        : "text-text2 hover:text-text hover:bg-hover/60"
                    }`}
                  >
                    <span
                      className={`absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r ${
                        active ? "bg-gold" : "bg-transparent"
                      }`}
                    />
                    <Icon className={`h-4 w-4 ${active ? "text-gold" : ""}`} />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <div className="px-3 py-3 border-t border-border bg-panel/40">
        <div className="text-sm font-semibold text-text truncate">{displayName}</div>
        <div className="text-[10px] tracking-[0.18em] font-semibold text-gold mb-2">{role}</div>
        <button
          type="button"
          onClick={() => logout()}
          className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-text hover:bg-hover min-h-[44px]"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign Out
        </button>
      </div>
    </>
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
      className={`hidden sm:inline-flex items-center gap-1.5 font-medium ${
        online ? "text-ok" : "text-err"
      }`}
      title={online ? `API ~${healthQ.data?.ms ?? "—"} ms` : "API unreachable"}
    >
      <Circle className="h-2 w-2 fill-current" />
      {online ? "Online" : "Offline"}
    </div>
  );
}

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const now = useClock();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);

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
  const unread = Number(notifQ.data?.unread || 0);
  const ver = versionQ.data?.version || "2.3.87";
  const build = versionQ.data?.build || "PROD-2026-07-18-v2.3.87";
  const exe = versionQ.data?.exe || "MBT_POS.exe";

  const dateStr = now
    ? now.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" })
    : "";
  const timeStr = now ? now.toLocaleTimeString("en-GB", { hour12: false }) : "--:--:--";

  const refresh = useCallback(() => {
    qc.invalidateQueries();
  }, [qc]);

  // Simple keyboard: `/` focuses search-like nav to dashboard via g then d
  useEffect(() => {
    let pendingG = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) {
        return;
      }
      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        navigate({ to: "/" });
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

  return (
    <div className="min-h-screen flex flex-col bg-app text-text">
      <div className="flex flex-1 min-h-0">
        {/* Desktop Sidebar */}
        <aside className="hidden lg:flex w-[228px] shrink-0 flex-col bg-sidebar border-r border-border">
          <SidebarContent />
        </aside>

        {/* Mobile drawer (More) */}
        {mobileOpen && (
          <div className="lg:hidden fixed inset-0 z-50 flex">
            <div
              className="absolute inset-0 bg-black/60"
              onClick={() => setMobileOpen(false)}
            />
            <aside className="relative w-[280px] max-w-[85vw] flex flex-col bg-sidebar border-r border-border shadow-2xl">
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-2 top-2 z-10 inline-flex items-center justify-center h-11 w-11 rounded-md text-text2 hover:bg-hover"
                aria-label="Close menu"
              >
                <X className="h-4 w-4" />
              </button>
              <SidebarContent onNavigate={() => setMobileOpen(false)} />
            </aside>
          </div>
        )}

        {/* Main */}
        <div className="flex-1 min-w-0 flex flex-col bg-surface">
          <header className="h-14 shrink-0 flex items-center justify-between gap-2 sm:gap-4 px-3 sm:px-6 border-b border-border bg-panel/60">
            <div className="flex items-center gap-2 min-w-0">
              <button
                onClick={() => setMobileOpen(true)}
                className="lg:hidden inline-flex items-center justify-center h-11 w-11 rounded-md border border-border bg-card text-text hover:bg-hover"
                aria-label="Open menu"
              >
                <Menu className="h-4 w-4" />
              </button>
              <h1 className="text-[15px] font-semibold text-text truncate">{title}</h1>
            </div>
            <div className="flex items-center gap-1.5 sm:gap-3 text-sm">
              <OnlineBadge />
              <Link
                to="/notifications"
                className="relative inline-flex items-center justify-center h-11 w-11 sm:h-9 sm:w-9 rounded-md border border-border bg-card text-text hover:bg-hover"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
                {unread > 0 ? (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-err text-[10px] font-bold text-white grid place-items-center">
                    {unread > 9 ? "9+" : unread}
                  </span>
                ) : null}
              </Link>
              <button
                type="button"
                onClick={refresh}
                className="hidden md:inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 hover:bg-hover text-text"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
              <ThemeToggle />
              <div className="hidden md:block text-text2 tabular-nums text-xs pl-2 border-l border-border">
                <span className="mr-3">{dateStr}</span>
                <span className="font-mono text-text">{timeStr}</span>
              </div>
            </div>
          </header>

          <main className="flex-1 min-h-0 overflow-y-auto scrollbar-thin overflow-x-hidden pb-[72px] lg:pb-0">
            <div className="p-3 sm:p-6 max-w-[1400px]">{children}</div>
          </main>

          <footer className="hidden lg:flex min-h-9 shrink-0 items-center justify-between gap-1 px-3 sm:px-6 py-1.5 border-t border-border bg-panel/60 text-[11px] text-text2">
            <span>MBT POS · MugoByte Technologies</span>
            <span className="font-mono truncate" title="Press / for dashboard">
              v{ver} · {build} · EXE:{exe}
            </span>
          </footer>
        </div>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-panel/95 backdrop-blur-sm safe-bottom">
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
                className={`flex flex-col items-center justify-center gap-0.5 min-h-[56px] text-[10px] font-semibold ${
                  active ? "text-gold" : "text-text2"
                }`}
              >
                <Icon className={`h-5 w-5 ${active ? "text-gold" : ""}`} />
                {item.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex flex-col items-center justify-center gap-0.5 min-h-[56px] text-[10px] font-semibold text-text2"
          >
            <MoreHorizontal className="h-5 w-5" />
            More
          </button>
        </div>
      </nav>
    </div>
  );
}
