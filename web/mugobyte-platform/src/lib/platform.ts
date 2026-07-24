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
  /** Visual grouping for My Products (separate sections, not a flat mixed list). */
  section: string;
  company?: string;
  version?: string;
  download_url?: string;
};

export type MarketplaceEntry = PlatformApp & {
  installed: boolean;
  update_available?: boolean;
};

export type AppSectionGroup = {
  section: string;
  apps: PlatformApp[];
};

/** Canonical section order — Point of Sale and Desktop utilities stay distinct. */
export const SECTION_ORDER = [
  "Point of Sale",
  "Desktop utilities",
  "Education",
  "Business operations",
  "Finance",
  "Industry",
  "Marketing & insights",
  "Platform",
] as const;

/** Fallback product catalog — must stay aligned with /api/platform/applications */
const FALLBACK_APPS: PlatformApp[] = [
  {
    id: "mbt-pos",
    name: "MBT POS",
    company: "MugoByte Technologies",
    description: "Cloud licenses, devices, backups and reports. Live ops on your shop tunnel.",
    icon: "pos",
    status: "active",
    launch_url: "/pos",
    permission: "mbt_pos",
    category: "Retail",
    section: "Point of Sale",
    version: "2.4.x",
    download_url:
      "https://github.com/MugoJnr/mbt-pos/releases/latest/download/MBT_POS_Setup.exe",
  },
  {
    id: "pulse",
    name: "Pulse",
    company: "MugoByte Technologies",
    description:
      "Desktop command center for CPU, GPU, memory and system health — same MugoByte Account as POS.",
    icon: "pulse",
    status: "active",
    launch_url: "/downloads#pulse",
    permission: "pulse",
    category: "System tools",
    section: "Desktop utilities",
    version: "1.0.x",
  },
  {
    id: "exam-hub",
    name: "Exam Hub",
    company: "MugoByte Technologies",
    description: "Students, teachers, exams and results for educational institutions.",
    icon: "exam",
    status: "coming_soon",
    launch_url: "#",
    permission: "exam_hub",
    category: "Education",
    section: "Education",
  },
  {
    id: "erp",
    name: "ERP",
    company: "MugoByte Technologies",
    description: "Enterprise resource planning for growing businesses.",
    icon: "erp",
    status: "coming_soon",
    launch_url: "#",
    permission: "erp",
    category: "Operations",
    section: "Business operations",
  },
  {
    id: "crm",
    name: "CRM",
    company: "MugoByte Technologies",
    description: "Customer relationships, pipelines and follow-ups.",
    icon: "crm",
    status: "coming_soon",
    launch_url: "#",
    permission: "crm",
    category: "Sales",
    section: "Business operations",
  },
  {
    id: "hr",
    name: "HR",
    company: "MugoByte Technologies",
    description: "People, attendance and payroll preparation.",
    icon: "hr",
    status: "coming_soon",
    launch_url: "#",
    permission: "hr",
    category: "People",
    section: "Business operations",
  },
  {
    id: "inventory",
    name: "Inventory Cloud",
    company: "MugoByte Technologies",
    description: "Multi-branch stock visibility and replenishment.",
    icon: "inventory",
    status: "coming_soon",
    launch_url: "#",
    permission: "inventory",
    category: "Operations",
    section: "Business operations",
  },
  {
    id: "accounting",
    name: "Accounting",
    company: "MugoByte Technologies",
    description: "Cloud ledgers and financial statements.",
    icon: "accounting",
    status: "coming_soon",
    launch_url: "#",
    permission: "accounting",
    category: "Finance",
    section: "Finance",
  },
  {
    id: "payroll",
    name: "Payroll",
    company: "MugoByte Technologies",
    description: "Salaries and payslips.",
    icon: "payroll",
    status: "coming_soon",
    launch_url: "#",
    permission: "payroll",
    category: "Finance",
    section: "Finance",
  },
  {
    id: "school",
    name: "School",
    company: "MugoByte Technologies",
    description: "Admissions, fees and school administration.",
    icon: "school",
    status: "coming_soon",
    launch_url: "#",
    permission: "school",
    category: "Education",
    section: "Education",
  },
  {
    id: "hospital",
    name: "Hospital",
    company: "MugoByte Technologies",
    description: "Clinics, patient records and billing.",
    icon: "hospital",
    status: "coming_soon",
    launch_url: "#",
    permission: "hospital",
    category: "Health",
    section: "Industry",
  },
  {
    id: "farm",
    name: "Farm Management",
    company: "MugoByte Technologies",
    description: "Farms, harvests, inventory and cooperative trading.",
    icon: "agriculture",
    status: "coming_soon",
    launch_url: "#",
    permission: "agriculture",
    category: "Agriculture",
    section: "Industry",
  },
  {
    id: "trading",
    name: "Trading Platform",
    company: "MugoByte Technologies",
    description: "Wholesale trading, pricing and partner networks.",
    icon: "trading",
    status: "coming_soon",
    launch_url: "#",
    permission: "trading",
    category: "Commerce",
    section: "Industry",
  },
  {
    id: "media",
    name: "MB Media",
    company: "MugoByte Technologies",
    description: "Brand assets, campaigns and content for your businesses.",
    icon: "media",
    status: "coming_soon",
    launch_url: "#",
    permission: "media",
    category: "Marketing",
    section: "Marketing & insights",
  },
  {
    id: "ai",
    name: "AI Hub",
    company: "MugoByte Technologies",
    description: "Insights, forecasting and assistants across products.",
    icon: "ai",
    status: "active",
    launch_url: "/ai",
    permission: "ai",
    category: "Insights",
    section: "Marketing & insights",
    version: "Beta",
  },
  {
    id: "marketplace",
    name: "Marketplace",
    company: "MugoByte Technologies",
    description: "Discover and install additional MugoByte products.",
    icon: "marketplace",
    status: "coming_soon",
    launch_url: "#",
    permission: "marketplace",
    category: "Platform",
    section: "Platform",
  },
  {
    id: "developer",
    name: "Developer Console",
    company: "MugoByte Technologies",
    description: "API keys, webhooks and integration tooling.",
    icon: "developer",
    status: "coming_soon",
    launch_url: "#",
    permission: "developer",
    category: "Platform",
    section: "Platform",
  },
];

const SECTION_FALLBACK: Record<string, string> = {
  "mbt-pos": "Point of Sale",
  pulse: "Desktop utilities",
  "exam-hub": "Education",
  school: "Education",
  erp: "Business operations",
  crm: "Business operations",
  hr: "Business operations",
  inventory: "Business operations",
  accounting: "Finance",
  payroll: "Finance",
  hospital: "Industry",
  farm: "Industry",
  trading: "Industry",
  media: "Marketing & insights",
  ai: "Marketing & insights",
  marketplace: "Platform",
  developer: "Platform",
};

export function resolveAppSection(app: PlatformApp): string {
  if (app.section?.trim()) return app.section.trim();
  return SECTION_FALLBACK[app.id] || app.category || "Other";
}

export function groupAppsBySection(apps: PlatformApp[]): AppSectionGroup[] {
  const buckets = new Map<string, PlatformApp[]>();
  for (const app of apps) {
    const section = resolveAppSection(app);
    const list = buckets.get(section) || [];
    list.push(app);
    buckets.set(section, list);
  }
  const ordered: AppSectionGroup[] = [];
  const seen = new Set<string>();
  for (const section of SECTION_ORDER) {
    const list = buckets.get(section);
    if (list?.length) {
      ordered.push({ section, apps: list });
      seen.add(section);
    }
  }
  for (const [section, list] of buckets) {
    if (!seen.has(section) && list.length) ordered.push({ section, apps: list });
  }
  return ordered;
}

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
    installed: a.id === "mbt-pos" || a.id === "pulse",
  }));
}

export function canLaunch(app: PlatformApp): boolean {
  return app.status === "active" || app.status === "read_only";
}

/** Product ids that can be issued from Admin → Licenses. */
export const LICENSE_PRODUCTS = [
  { id: "mbt-pos", name: "MBT POS", section: "Point of Sale" },
  { id: "pulse", name: "Pulse", section: "Desktop utilities" },
  { id: "exam-hub", name: "Exam Hub", section: "Education" },
] as const;
