import { Link, useNavigate } from "@tanstack/react-router";
import { Bell, Search, Moon, Sun, Monitor, LogOut, User, Settings, Building2, LayoutGrid, HelpCircle, Check } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/lib/auth";
import { ProductSwitcher } from "@/components/layout/ProductSwitcher";
import { fetchOrganizations } from "@/lib/platform";
import { BRAND } from "@/lib/brand";

function TopbarLogo() {
  const { theme } = useTheme();
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  return (
    <img
      src={isDark ? BRAND.companyLogoDark : BRAND.companyLogo}
      alt="MugoByte"
      className="h-7 w-auto max-w-[180px] object-contain object-left sm:max-w-[200px]"
      draggable={false}
    />
  );
}

export function AppTopbar({ title }: { title?: string }) {
  const { theme, setTheme } = useTheme();
  const { user, logout, orgId, setActiveOrg } = useAuth();
  const navigate = useNavigate();
  const orgsQ = useQuery({ queryKey: ["platform-orgs"], queryFn: fetchOrganizations });
  const orgs = orgsQ.data || [];
  const activeOrg = orgs.find((o) => o.id === orgId) || orgs[0];
  const initials = String(user?.full_name || user?.username || "MB")
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/60 sm:px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 h-5" />
      <Link
        to="/dashboard"
        className="mr-1 inline-flex shrink-0 items-center rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring sm:hidden"
        aria-label="MugoByte Workspace home"
      >
        <TopbarLogo />
      </Link>
      <div className="hidden min-w-[10rem] max-w-[16rem] sm:block lg:max-w-[20rem]">
        <div
          className="truncate font-display text-sm font-semibold leading-tight"
          title={title || "MugoByte Workspace"}
        >
          {title || "MugoByte Workspace"}
        </div>
        <div
          className="truncate text-[10px] text-muted-foreground"
          title={activeOrg?.name || "Select a business"}
        >
          {activeOrg?.name || "Select a business"}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        <Button
          asChild
          variant="outline"
          className="hidden h-9 gap-2 rounded-full px-3 lg:inline-flex"
        >
          <Link to="/reports" aria-label="Open cloud reports search">
            <Search className="h-4 w-4" />
            <span className="text-sm text-muted-foreground">Search reports…</span>
          </Link>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              className="hidden h-9 max-w-[18rem] gap-2 md:inline-flex"
              title={activeOrg?.name || "Business"}
            >
              <Building2 className="h-4 w-4 shrink-0" />
              <span className="truncate">{activeOrg?.name || "Business"}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuLabel>Switch business</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {orgs.map((org) => {
              const active = activeOrg?.id === org.id;
              return (
                <DropdownMenuItem key={org.id} onClick={() => setActiveOrg(org.id)} className="gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{org.name}</div>
                    <div className="text-xs text-muted-foreground">{org.role || "member"}</div>
                  </div>
                  {active ? <Check className="h-4 w-4 text-primary" /> : null}
                </DropdownMenuItem>
              );
            })}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/businesses">Manage businesses</Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button asChild variant="ghost" size="icon" aria-label="Workspace home" className="h-9 w-9">
          <Link to="/dashboard">
            <LayoutGrid className="h-4 w-4" />
          </Link>
        </Button>

        <ProductSwitcher />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Theme" className="h-9 w-9">
              {theme === "light" ? (
                <Sun className="h-4 w-4" />
              ) : theme === "dark" ? (
                <Moon className="h-4 w-4" />
              ) : (
                <Monitor className="h-4 w-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-36">
            <DropdownMenuItem onClick={() => setTheme("light")}>
              <Sun className="mr-2 h-4 w-4" />
              Light
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("dark")}>
              <Moon className="mr-2 h-4 w-4" />
              Dark
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("system")}>
              <Monitor className="mr-2 h-4 w-4" />
              System
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button asChild variant="ghost" size="icon" aria-label="Help" className="h-9 w-9">
          <Link to="/support">
            <HelpCircle className="h-4 w-4" />
          </Link>
        </Button>

        <Button asChild variant="ghost" size="icon" aria-label="Notifications" className="relative h-9 w-9">
          <Link to="/notifications">
            <Bell className="h-4 w-4" />
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-primary ring-2 ring-background" />
          </Link>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="h-9 gap-2 pl-1 pr-2"
              aria-label={`Account menu for ${user?.full_name || user?.username || "MugoByte User"}`}
            >
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
                  {initials || "MB"}
                </AvatarFallback>
              </Avatar>
              <div className="hidden text-left sm:block">
                <div className="text-xs font-medium leading-none">
                  {user?.full_name || user?.username || "MugoByte User"}
                </div>
                <div className="mt-0.5 text-[10px] leading-none text-muted-foreground">
                  {activeOrg?.name || "No business selected"}
                </div>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="flex items-center justify-between">
              <span>My account</span>
              <Badge variant="secondary" className="text-[10px]">
                {String(user?.role || "member")}
              </Badge>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/account">
                <User className="mr-2 h-4 w-4" />
                Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to="/settings">
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => {
                logout();
                navigate({ to: "/login" });
              }}
            >
              <LogOut className="mr-2 h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
