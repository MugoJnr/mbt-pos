import { useQuery } from "@tanstack/react-query";
import { BRAND } from "@/lib/brand";
import { GET } from "@/lib/api";
import { cn } from "@/lib/utils";

const YEAR = new Date().getFullYear();

export function AppFooter({ className }: { className?: string }) {
  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<{ version?: string; build?: string }>("/version"),
    staleTime: 600_000,
    retry: false,
  });
  const healthQ = useQuery({
    queryKey: ["portal-health"],
    queryFn: async () => {
      const r = await fetch("/api/health");
      return r.ok;
    },
    refetchInterval: 60_000,
    retry: false,
  });
  const ver = versionQ.data?.version || "cloud";
  const build = versionQ.data?.build || "portal";
  const online = healthQ.data !== false;

  return (
    <footer
      className={cn(
        "mt-auto border-t border-border bg-muted/20 px-4 py-3 text-[11px] text-muted-foreground sm:px-6",
        className,
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-medium text-foreground">{BRAND.company}</span>
          <span className="hidden sm:inline">·</span>
          <span className="font-mono">
            v{ver} · {build}
          </span>
          <span className="hidden sm:inline">·</span>
          <span className={online ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}>
            {online ? "Connected" : "Offline"}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <a
            className="brand-interactive hover:text-foreground"
            href="https://mugobyte.com/privacy"
            target="_blank"
            rel="noreferrer"
          >
            Privacy
          </a>
          <a
            className="brand-interactive hover:text-foreground"
            href="https://mugobyte.com/terms"
            target="_blank"
            rel="noreferrer"
          >
            Terms
          </a>
          <a
            className="brand-interactive hover:text-foreground"
            href="https://docs.mugobyte.com"
            target="_blank"
            rel="noreferrer"
          >
            Docs
          </a>
          <a className="brand-interactive hover:text-foreground" href="/support">
            Support
          </a>
          <span>© {YEAR}</span>
        </div>
      </div>
    </footer>
  );
}
