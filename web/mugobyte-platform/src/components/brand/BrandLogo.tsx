import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { useTheme } from "@/lib/theme";

type BrandLogoProps = {
  /** Where the logo navigates. Portal: /dashboard. Live: /. */
  to: string;
  /**
   * icon = company mark only
   * wordmark = official company logo image (preferred)
   * full = same as wordmark (legacy alias)
   * stacked = logo + optional subtitle line
   */
  variant?: "icon" | "wordmark" | "full" | "stacked";
  title?: string;
  subtitle?: string;
  collapsed?: boolean;
  className?: string;
  imgClassName?: string;
};

function useCompanyLogoSrc() {
  const { theme } = useTheme();
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  return {
    src: isDark ? BRAND.companyLogoDark : BRAND.companyLogo,
    srcSet: isDark
      ? `${BRAND.companyLogoDark} 1x, ${BRAND.companyLogoDark2x} 2x`
      : `${BRAND.companyLogo} 1x, ${BRAND.companyLogo2x} 2x`,
  };
}

/**
 * Official clickable MugoByte logo.
 * Preserves SPA navigation (no full reload) and auth session.
 */
export function BrandLogo({
  to,
  variant = "wordmark",
  title = "MugoByte Workspace",
  subtitle,
  collapsed = false,
  className,
  imgClassName,
}: BrandLogoProps) {
  const showWordmark = !collapsed && (variant === "wordmark" || variant === "full" || variant === "stacked");
  const logo = useCompanyLogoSrc();

  if (collapsed || variant === "icon") {
    return (
      <Link
        to={to as "/dashboard"}
        className={cn(
          "brand-interactive inline-flex items-center outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background rounded-lg",
          className,
        )}
        aria-label={`${title} — go home`}
      >
        <img
          src={BRAND.markSvg}
          alt=""
          className={cn(
            "h-9 w-9 shrink-0 rounded-lg object-cover shadow-sm ring-1 ring-border/60",
            imgClassName,
          )}
          draggable={false}
        />
      </Link>
    );
  }

  return (
    <Link
      to={to as "/dashboard"}
      className={cn(
        "brand-interactive flex flex-col items-start gap-1 rounded-lg px-0.5 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
      aria-label={`${title} — go home`}
    >
      <img
        src={logo.src}
        srcSet={logo.srcSet}
        alt="MugoByte Technologies"
        className={cn(
          "h-9 w-auto max-w-[168px] object-contain object-left drop-shadow-sm sm:h-10 sm:max-w-[190px]",
          imgClassName,
        )}
        draggable={false}
      />
      {showWordmark && variant === "stacked" && subtitle ? (
        <div className="pl-0.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground truncate max-w-[190px]">
          {subtitle}
        </div>
      ) : null}
    </Link>
  );
}
