import type { ReactNode } from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ReportState({
  loading,
  error,
  empty,
  onRetry,
  children,
}: {
  loading: boolean;
  error?: string | null;
  empty: boolean;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div
        className="grid min-h-64 place-items-center text-sm text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        <span className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading analytics…
        </span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="grid min-h-64 place-items-center px-4 text-center" role="alert">
        <div>
          <AlertCircle className="mx-auto mb-3 h-7 w-7 text-destructive" />
          <p className="font-medium">Analytics could not be loaded</p>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <Button className="mt-4" size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        </div>
      </div>
    );
  }
  if (empty) {
    return (
      <div
        className="grid min-h-64 place-items-center px-4 text-center text-sm text-muted-foreground"
        role="status"
      >
        <div>
          <Inbox className="mx-auto mb-3 h-7 w-7" />
          No matching records for this date range.
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

export function responseError(data: { error?: string } | null | undefined, queryError: unknown) {
  if (data?.error) return data.error;
  if (queryError instanceof Error) return queryError.message;
  return queryError ? "An unexpected request error occurred." : null;
}
