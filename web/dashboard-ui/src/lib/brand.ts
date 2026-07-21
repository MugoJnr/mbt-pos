/** Official MugoByte brand — single source of truth for Live Dashboard SPA. */
export const BRAND = {
  name: "MugoByte",
  company: "MugoByte Technologies",
  platform: "MugoByte Platform",
  tagline: "Live operational dashboard",
  portalUrl: "https://portal.mugobyte.com",
  markSvg: "/favicon.svg",
  logoHd: "/brand/mbt_logo_hd.png",
  icon: "/brand/mbt_icon.png",
  icon64: "/brand/mbt_icon_64.png",
  faviconIco: "/favicon.ico",
  faviconSvg: "/favicon.svg",
  appleTouch: "/apple-touch-icon.png",
  ogImage: "/brand/og-card.png",
} as const;

/** Browser tab titles: `{Section} · Live Dashboard | MugoByte` or `Live Dashboard | MugoByte`. */
export function pageTitle(product: string, section?: string): string {
  const base = `${product} | MugoByte`;
  return section ? `${section} · ${base}` : base;
}

export const LIVE_PRODUCT = "Live Dashboard";
export const POS_PRODUCT = "MBT POS";
