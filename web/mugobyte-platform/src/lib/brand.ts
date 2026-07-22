/** Official MugoByte brand — single source of truth for Portal SPA. */
export const BRAND = {
  name: "MugoByte",
  company: "MugoByte Technologies",
  platform: "MugoByte Platform",
  tagline: "One Account. Every MugoByte Product.",
  portalUrl: "https://portal.mugobyte.com",
  docsUrl: "https://docs.mugobyte.com",
  privacyUrl: "https://mugobyte.com/privacy",
  termsUrl: "https://mugobyte.com/terms",
  /** Company/platform mark (letter M). Prefer for compact chrome. */
  markSvg: "/favicon.svg",
  /**
   * Official MugoByte company wordmark (shield + MugoByte Technologies).
   * Use on Workspace chrome, auth, and marketing surfaces.
   */
  companyLogo: "/brand/mugo_logo.png",
  companyLogoDark: "/brand/mugo_logo_dark.png",
  companyLogo2x: "/brand/mugo_logo_2x.png",
  companyLogoDark2x: "/brand/mugo_logo_dark_2x.png",
  /** MBT POS product monitor art — use only on POS product surfaces. */
  logoHd: "/brand/mbt_logo_hd.png",
  icon: "/brand/mbt_icon.png",
  icon64: "/brand/mbt_icon_64.png",
  faviconIco: "/favicon.ico",
  faviconSvg: "/favicon.svg",
  appleTouch: "/apple-touch-icon.png",
  ogImage: "/brand/og-card.png",
} as const;

/** Browser tab titles: `{Section} | MugoByte` or `{Product} | MugoByte`. */
export function pageTitle(productOrSection: string, section?: string): string {
  if (section) return `${section} | MugoByte`;
  return `${productOrSection} | MugoByte`;
}

export const PORTAL_PRODUCT = "MugoByte Workspace";
export const PLATFORM_PRODUCT = "MugoByte Platform";
export const LIVE_PRODUCT = "Live Dashboard";
export const POS_PRODUCT = "MBT POS";
export const POS_CLOUD_PRODUCT = "MBT POS Cloud";
