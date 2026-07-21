import type { ComponentType } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  BarChart3,
  MonitorSmartphone,
  KeyRound,
  CloudUpload,
  Bell,
  Settings,
  LifeBuoy,
  Store,
  Users,
  ScrollText,
  Activity,
  Sparkles,
  Download,
  Building2,
  Shield,
  Package,
  CreditCard,
  HelpCircle,
  Bot,
  LayoutGrid,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { BrandLogo } from "@/components/brand/BrandLogo";

type NavItem = { title: string; url: string; icon: ComponentType<{ className?: string }>; badge?: string };
type NavGroup = { label: string; items: NavItem[] };

const workspaceNav: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { title: "Home", url: "/dashboard", icon: LayoutDashboard },
      { title: "My Products", url: "/dashboard#products", icon: LayoutGrid },
      { title: "Businesses", url: "/businesses", icon: Building2 },
      { title: "Devices", url: "/devices", icon: MonitorSmartphone },
      { title: "Reports", url: "/reports", icon: BarChart3 },
      { title: "Notifications", url: "/notifications", icon: Bell },
      { title: "Downloads", url: "/downloads", icon: Download },
      { title: "Support", url: "/support", icon: LifeBuoy },
      { title: "Billing", url: "/billing", icon: CreditCard, badge: "Soon" },
      { title: "Settings", url: "/settings", icon: Settings },
    ],
  },
  {
    label: "MBT POS Cloud",
    items: [
      { title: "Overview", url: "/pos", icon: Package },
      { title: "Reports", url: "/reports", icon: BarChart3 },
      { title: "Devices", url: "/devices", icon: MonitorSmartphone },
      { title: "Licenses", url: "/license", icon: KeyRound },
      { title: "Backups", url: "/backups", icon: CloudUpload },
      { title: "Branches", url: "/branches", icon: Store },
      { title: "Users", url: "/users", icon: Users },
      { title: "Notifications", url: "/notifications", icon: Bell },
      { title: "Downloads", url: "/downloads", icon: Download },
      { title: "Security", url: "/security", icon: Shield },
      { title: "AI Insights", url: "/ai", icon: Bot, badge: "Beta" },
    ],
  },
];

const adminNav: NavGroup[] = [
  {
    label: "Platform Admin",
    items: [
      { title: "Overview", url: "/admin", icon: LayoutDashboard },
      { title: "Organizations", url: "/admin/shops", icon: Store },
      { title: "Users", url: "/admin/users", icon: Users },
      { title: "Licenses", url: "/admin/licenses", icon: KeyRound },
      { title: "Devices", url: "/admin/devices", icon: MonitorSmartphone },
      { title: "Updates", url: "/admin/updates", icon: Download },
      { title: "Audit Logs", url: "/admin/audit-logs", icon: ScrollText },
      { title: "System Health", url: "/admin/system-health", icon: Activity },
      { title: "Feature Flags", url: "/admin/feature-flags", icon: Sparkles },
      { title: "Analytics", url: "/admin/analytics", icon: BarChart3 },
      { title: "Settings", url: "/admin/settings", icon: Settings },
    ],
  },
];

function isPlatformAdmin(role?: string) {
  return (role || "").toLowerCase() === "platform_admin";
}

export function AppSidebar({ variant = "customer" }: { variant?: "customer" | "admin" }) {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const { user } = useAuth();
  const showAdmin = variant === "admin" || isPlatformAdmin(user?.role);

  const groups =
    variant === "admin"
      ? adminNav
      : showAdmin
        ? [...workspaceNav, ...adminNav]
        : workspaceNav;

  const isActive = (url: string) => {
    const path = url.split("#")[0];
    if (path === "/admin") return pathname === "/admin";
    if (path === "/dashboard") return pathname === "/dashboard";
    if (path === "/pos") return pathname === "/pos" || pathname.startsWith("/pos/");
    return pathname === path || pathname.startsWith(path + "/");
  };

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border">
      <SidebarHeader className="border-b border-sidebar-border">
        <div className="px-2 py-1.5">
          <BrandLogo
            to="/dashboard"
            title="MugoByte Workspace"
            subtitle="One account · Every product"
            collapsed={collapsed}
          />
        </div>
      </SidebarHeader>

      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group.label}>
            {!collapsed && <SidebarGroupLabel>{group.label}</SidebarGroupLabel>}
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => (
                  <SidebarMenuItem key={`${group.label}-${item.url}`}>
                    <SidebarMenuButton asChild isActive={isActive(item.url)} tooltip={item.title}>
                      <Link to={item.url.split("#")[0] as "/dashboard"} className="flex items-center gap-2">
                        <item.icon className="h-4 w-4 shrink-0" />
                        {!collapsed && <span className="flex-1 truncate">{item.title}</span>}
                        {!collapsed && item.badge && (
                          <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                            {item.badge}
                          </Badge>
                        )}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-2">
        {!collapsed && (
          <div className="flex items-start gap-2 rounded-lg bg-muted/40 px-2 py-2 text-[10px] text-muted-foreground">
            <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Live shop ops stay on <span className="text-foreground">{"{shop}.mugobyte.com"}</span> — this portal is cloud only.
            </span>
          </div>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
