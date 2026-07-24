import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[11px] font-semibold uppercase tracking-widest text-primary">{eyebrow}</p>
        )}
        <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact
          ? "flex flex-col items-center justify-center rounded-lg border border-dashed border-border/70 bg-card/20 px-4 py-8 text-center animate-fade-in"
          : "flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/30 px-6 py-16 text-center animate-fade-in"
      }
    >
      <div
        className={
          compact
            ? "grid h-10 w-10 place-items-center rounded-full bg-primary/10 text-primary"
            : "grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary"
        }
      >
        <Icon className={compact ? "h-5 w-5" : "h-6 w-6"} />
      </div>
      <h3 className={`mt-3 font-display font-semibold ${compact ? "text-sm" : "mt-4 text-base"}`}>
        {title}
      </h3>
      {description && (
        <p className={`mt-1 max-w-sm text-muted-foreground ${compact ? "text-xs" : "text-sm"}`}>
          {description}
        </p>
      )}
      {actionLabel && (
        <Button className="mt-5" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6 p-4 pb-16 sm:p-6 sm:pb-20 lg:p-8 lg:pb-24 animate-fade-in">
      {children}
    </div>
  );
}
