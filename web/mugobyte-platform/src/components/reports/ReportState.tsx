import type { ReactNode } from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ReportState({
  loading,
  error,
  empty,
  emptyTitle,
  emptyHint,
  onRetry,
  children,
}: {
  loading: boolean;
  error?: string | null;
  empty: boolean;
  emptyTitle?: string;
  emptyHint?: string;
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
        <div className="max-w-md">
          <Inbox className="mx-auto mb-3 h-7 w-7" />
          <p className="font-medium text-foreground">
            {emptyTitle || "No matching records for this date range."}
          </p>
          {emptyHint ? <p className="mt-2 text-sm">{emptyHint}</p> : null}
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
