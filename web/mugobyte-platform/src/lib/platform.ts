import { GET } from "./api";
import type { Organization } from "./auth";

export type PlatformApp = {
  id: string;
  name: string;
  description: string;
  icon: string;
  status: "active" | "disabled" | "coming_soon" | "read_only";
  launch_url: string;
  permission: string;
  category: string;
  version?: string;
};

export type MarketplaceEntry = PlatformApp & {
  installed: boolean;
  update_available?: boolean;
};

/** Fallback product catalog — must stay aligned with /api/platform/applications */
const FALLBACK_APPS: PlatformApp[] = [
  {
    id: "mbt-pos",
    name: "MBT POS",
    description: "Cloud licenses, devices, backups and reports. Live ops on your shop tunnel.",
    icon: "pos",
    status: "active",
    launch_url: "/pos",
    permission: "mbt_pos",
    category: "Retail",
    version: "2.4.x",
  },
  {
    id: "exam-hub",
    name: "Exam Hub",
    description: "Students, teachers, exams and results for educational institutions.",
    icon: "exam",
    status: "coming_soon",
    launch_url: "#",
    permission: "exam_hub",
    category: "Education",
  },
  {
    id: "erp",
    name: "ERP",
    description: "Enterprise resource planning for growing businesses.",
    icon: "erp",
    status: "coming_soon",
    launch_url: "#",
    permission: "erp",
    category: "Operations",
  },
  {
    id: "crm",
    name: "CRM",
    description: "Customer relationships, pipelines and follow-ups.",
    icon: "crm",
    status: "coming_soon",
    launch_url: "#",
    permission: "crm",
    category: "Sales",
  },
  {
    id: "hr",
    name: "HR",
    description: "People, attendance and payroll preparation.",
    icon: "hr",
    status: "coming_soon",
    launch_url: "#",
    permission: "hr",
    category: "People",
  },
  {
    id: "inventory",
    name: "Inventory Cloud",
    description: "Multi-branch stock visibility and replenishment.",
    icon: "inventory",
    status: "coming_soon",
    launch_url: "#",
    permission: "inventory",
    category: "Operations",
  },
  {
    id: "accounting",
    name: "Accounting",
    description: "Cloud ledgers and financial statements.",
    icon: "accounting",
    status: "coming_soon",
    launch_url: "#",
    permission: "accounting",
    category: "Finance",
  },
  {
    id: "payroll",
    name: "Payroll",
    description: "Salaries and payslips.",
    icon: "payroll",
    status: "coming_soon",
    launch_url: "#",
    permission: "payroll",
    category: "Finance",
  },
  {
    id: "school",
    name: "School",
    description: "Admissions, fees and school administration.",
    icon: "school",
    status: "coming_soon",
    launch_url: "#",
    permission: "school",
    category: "Education",
  },
  {
    id: "hospital",
    name: "Hospital",
    description: "Clinics, patient records and billing.",
    icon: "hospital",
    status: "coming_soon",
    launch_url: "#",
    permission: "hospital",
    category: "Health",
  },
  {
    id: "farm",
    name: "Farm Management",
    description: "Farms, harvests, inventory and cooperative trading.",
    icon: "agriculture",
    status: "coming_soon",
    launch_url: "#",
    permission: "agriculture",
    category: "Agriculture",
  },
  {
    id: "trading",
    name: "Trading Platform",
    description: "Wholesale trading, pricing and partner networks.",
    icon: "trading",
    status: "coming_soon",
    launch_url: "#",
    permission: "trading",
    category: "Commerce",
  },
  {
    id: "media",
    name: "MB Media",
    description: "Brand assets, campaigns and content for your businesses.",
    icon: "media",
    status: "coming_soon",
    launch_url: "#",
    permission: "media",
    category: "Marketing",
  },
  {
    id: "ai",
    name: "AI Hub",
    description: "Insights, forecasting and assistants across products.",
    icon: "ai",
    status: "active",
    launch_url: "/ai",
    permission: "ai",
    category: "Insights",
    version: "Beta",
  },
  {
    id: "marketplace",
    name: "Marketplace",
    description: "Discover and install additional MugoByte products.",
    icon: "marketplace",
    status: "coming_soon",
    launch_url: "#",
    permission: "marketplace",
    category: "Platform",
  },
  {
    id: "developer",
    name: "Developer Console",
    description: "API keys, webhooks and integration tooling.",
    icon: "developer",
    status: "coming_soon",
    launch_url: "#",
    permission: "developer",
    category: "Platform",
  },
];

export async function fetchOrganizations(): Promise<Organization[]> {
  const res = await GET<{ organizations?: Organization[] }>("/platform/organizations");
  if (res?.organizations?.length) return res.organizations;
  return [{ id: "default", name: "My Business", slug: "default", role: "owner", is_primary: true }];
}

export async function fetchApplications(orgId?: string): Promise<PlatformApp[]> {
  const res = await GET<{ applications?: PlatformApp[] }>(
    "/platform/applications",
    orgId ? { org_id: orgId } : undefined,
  );
  if (res?.applications?.length) return res.applications;
  return FALLBACK_APPS;
}

export async function fetchMarketplace(orgId?: string): Promise<MarketplaceEntry[]> {
  const res = await GET<{ marketplace?: MarketplaceEntry[] }>(
    "/platform/marketplace",
    orgId ? { org_id: orgId } : undefined,
  );
  if (res?.marketplace?.length) return res.marketplace;
  return FALLBACK_APPS.map((a) => ({
    ...a,
    installed: a.id === "mbt-pos",
  }));
}

export function canLaunch(app: PlatformApp): boolean {
  return app.status === "active" || app.status === "read_only";
}
