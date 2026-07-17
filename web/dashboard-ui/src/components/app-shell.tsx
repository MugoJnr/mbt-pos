import { Link, useLocation } from "@tanstack/react-router";
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
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTheme } from "./theme";
import { useAuth } from "@/lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/pos", label: "Point of Sale", icon: ShoppingCart },
  { to: "/inventory", label: "Inventory", icon: Package },
  { to: "/debt", label: "Debt Management", icon: Banknote },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/notes", label: "Notes", icon: NotebookPen },
  { to: "/users", label: "Users & Access", icon: Users },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/security", label: "Security", icon: ShieldCheck, super: true },
  { to: "/license", label: "License", icon: KeyRound, super: true },
  { to: "/diagnostics", label: "Diagnostics", icon: Wrench },
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
      className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-text hover:bg-hover transition-colors"
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
  const displayName =
    user?.full_name || user?.username || "Staff";
  const role = String(user?.role || "cashier").toUpperCase();

  return (
    <>
      <div className="px-4 py-5 border-b border-border flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-gold text-sm font-black text-[color:var(--gold-fg)] shadow-[0_2px_8px_rgba(242,168,0,0.35)]">
          MBT
        </div>
        <div className="leading-tight">
          <div className="font-display font-extrabold text-gold text-lg tracking-wide">MBT</div>
          <div className="text-[10px] tracking-[0.22em] text-text2 font-semibold">POS SYSTEM</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto scrollbar-thin py-3 px-2">
        {NAV.map((item) => {
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
      </nav>

      <div className="px-3 py-3 border-t border-border bg-panel/40">
        <div className="text-sm font-semibold text-text truncate">{displayName}</div>
        <div className="text-[10px] tracking-[0.18em] font-semibold text-gold mb-2">{role}</div>
        <button
          type="button"
          onClick={() => logout()}
          className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-text hover:bg-hover"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign Out
        </button>
      </div>
    </>
  );
}

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const now = useClock();
  const [mobileOpen, setMobileOpen] = useState(false);

  const dateStr = now
    ? now.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" })
    : "";
  const timeStr = now ? now.toLocaleTimeString("en-GB", { hour12: false }) : "--:--:--";

  return (
    <div className="min-h-screen flex flex-col bg-app text-text">
      <div className="flex flex-1 min-h-0">
        {/* Desktop Sidebar */}
        <aside className="hidden lg:flex w-[228px] shrink-0 flex-col bg-sidebar border-r border-border">
          <SidebarContent />
        </aside>

        {/* Mobile drawer */}
        {mobileOpen && (
          <div className="lg:hidden fixed inset-0 z-50 flex">
            <div
              className="absolute inset-0 bg-black/60"
              onClick={() => setMobileOpen(false)}
            />
            <aside className="relative w-[260px] max-w-[80vw] flex flex-col bg-sidebar border-r border-border shadow-2xl">
              <button
                onClick={() => setMobileOpen(false)}
                className="absolute right-2 top-2 z-10 inline-flex items-center justify-center h-8 w-8 rounded-md text-text2 hover:bg-hover"
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
          {/* Topbar */}
          <header className="h-14 shrink-0 flex items-center justify-between gap-2 sm:gap-4 px-3 sm:px-6 border-b border-border bg-panel/60">
            <div className="flex items-center gap-2 min-w-0">
              <button
                onClick={() => setMobileOpen(true)}
                className="lg:hidden inline-flex items-center justify-center h-9 w-9 rounded-md border border-border bg-card text-text hover:bg-hover"
                aria-label="Open menu"
              >
                <Menu className="h-4 w-4" />
              </button>
              <h1 className="text-[15px] font-semibold text-text truncate">{title}</h1>
            </div>
            <div className="flex items-center gap-2 sm:gap-3 text-sm">
              <div className="hidden sm:inline-flex items-center gap-1.5 text-ok font-medium">
                <Circle className="h-2 w-2 fill-current" /> Online
              </div>
              <button className="hidden md:inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 hover:bg-hover text-text">
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </button>
              <ThemeToggle />
              <div className="hidden md:block text-text2 tabular-nums text-xs pl-2 border-l border-border">
                <span className="mr-3">{dateStr}</span>
                <span className="font-mono text-text">{timeStr}</span>
              </div>
            </div>
          </header>

          {/* Page */}
          <main className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
            <div className="p-3 sm:p-6">{children}</div>
          </main>

          {/* Footer */}
          <footer className="min-h-9 shrink-0 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 px-3 sm:px-6 py-1.5 border-t border-border bg-panel/60 text-[11px] text-text2">
            <span>MBT POS · MugoByte Technologies</span>
            <span className="font-mono truncate">v2.3.21 · PROD-2026-07-16 · EXE:MBT_POS.exe</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
