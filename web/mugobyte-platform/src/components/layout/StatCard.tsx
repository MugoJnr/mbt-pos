import type { LucideIcon } from "lucide-react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  icon: Icon,
  delta,
  trend = "up",
  hint,
  accent,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  delta?: string;
  trend?: "up" | "down" | "flat";
  hint?: string;
  accent?: "primary" | "success" | "warning" | "info" | "destructive";
}) {
  const accentClass = {
    primary: "bg-primary/10 text-primary",
    success: "bg-success/15 text-success",
    warning: "bg-warning/15 text-warning",
    info: "bg-info/15 text-info",
    destructive: "bg-destructive/15 text-destructive",
  }[accent ?? "primary"];

  return (
    <Card className="group relative overflow-hidden border-border/60 transition-all hover:border-border hover:shadow-elegant animate-fade-in">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
            <p
              className="mt-2 font-display text-xl font-semibold tracking-tight tabular-nums leading-tight sm:text-2xl"
              title={value}
            >
              {value}
            </p>
            {(delta || hint) && (
              <div className="mt-2 flex items-center gap-1.5 text-xs">
                {delta && (
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-medium",
                      trend === "up" && "bg-success/10 text-success",
                      trend === "down" && "bg-destructive/10 text-destructive",
                      trend === "flat" && "bg-muted text-muted-foreground",
                    )}
                  >
                    {trend === "up" ? <ArrowUpRight className="h-3 w-3" /> : trend === "down" ? <ArrowDownRight className="h-3 w-3" /> : null}
                    {delta}
                  </span>
                )}
                {hint && <span className="text-muted-foreground truncate">{hint}</span>}
              </div>
            )}
          </div>
          <div className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-lg", accentClass)}>
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
