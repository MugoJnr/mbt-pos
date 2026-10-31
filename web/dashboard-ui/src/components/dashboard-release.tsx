import { useEffect, useSyncExternalStore } from "react";
import { toast } from "sonner";
import {
  getDashboardRelease,
  refreshToLatestVersion,
  startDashboardReleaseCheck,
  subscribeDashboardRelease,
} from "@/lib/dashboard-release";

function useRelease() {
  useEffect(() => {
    startDashboardReleaseCheck();
  }, []);
  return useSyncExternalStore(subscribeDashboardRelease, getDashboardRelease, getDashboardRelease);
}

export function DashboardRefreshControl() {
  const snap = useRelease();
  useEffect(() => {
    if (snap.verified) toast.success(snap.verified);
  }, [snap.verified]);
  const show = snap.mismatch || snap.phase === "working" || snap.phase === "failed";
  if (!show) return null;
  const percent = snap.percent;
  const label = snap.phase === "working"
    ? (percent == null ? "Refreshing dashboard…" : `Refreshing dashboard… ${percent}%`)
    : "Refresh Dashboard to Latest Version";
  return (
    <div className="inline-flex max-w-[280px] flex-col gap-1">
      <button
        type="button"
        className="inline-flex items-center rounded-lg border border-amber-500/50 bg-amber-500/15 px-2.5 py-1.5 text-left text-xs font-bold text-text hover:bg-amber-500/25"
        onClick={() => void refreshToLatestVersion()}
        disabled={snap.phase === "working"}
      >
        {label}
      </button>
      {snap.phase === "working" && percent != null ? (
        <div className="h-1.5 overflow-hidden rounded-full bg-panel">
          <div className="h-full bg-gold" style={{ width: `${percent}%` }} />
        </div>
      ) : null}
      {snap.phase === "failed" && snap.message ? (
        <div className="text-[11px] leading-snug text-amber-200">{snap.message}</div>
      ) : null}
    </div>
  );
}
