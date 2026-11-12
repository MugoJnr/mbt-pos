/** Same short lines as the till update strip. No install work happens here. */

export type UpdateSessionState =
  | "idle"
  | "available"
  | "downloading"
  | "verifying"
  | "complete"
  | "installing"
  | "failed";

export type UpdateSessionView = {
  state: UpdateSessionState;
  title: string;
  detail: string;
  percent: number | null;
  bar: "hidden" | "busy" | "percent";
  visible: boolean;
};

export function updateSessionCopy(
  state: string,
  version = "",
  percent?: number | null,
  detail = "",
): UpdateSessionView {
  const ver = version ? `v${version}` : "the update";
  const pct = typeof percent === "number" && Number.isFinite(percent)
    ? Math.max(0, Math.min(100, Math.round(percent)))
    : null;
  if (state === "available") {
    return {
      state, title: `Update ${ver} found`,
      detail: "Download is starting. You can keep selling.",
      percent: null, bar: "busy", visible: true,
    };
  }
  if (state === "downloading") {
    return {
      state, title: `Downloading ${ver}`,
      detail: "You can keep selling.",
      percent: pct, bar: pct == null ? "busy" : "percent", visible: true,
    };
  }
  if (state === "verifying") {
    return {
      state: "verifying", title: "Checking the download",
      detail: "Almost ready.",
      percent: null, bar: "busy", visible: true,
    };
  }
  if (state === "complete") {
    return {
      state, title: `${ver} is ready`,
      detail: "Install it on the till. The till will close and reopen. Your sales stay.",
      percent: 100, bar: "percent", visible: true,
    };
  }
  if (state === "installing") {
    return {
      state, title: `Installing ${ver}`,
      detail: "The till will close and reopen.",
      percent: null, bar: "busy", visible: true,
    };
  }
  if (state === "failed") {
    const line = (detail || "Try again.").replace(/\s+/g, " ").slice(0, 120);
    return {
      state: "failed", title: "Update did not finish",
      detail: line, percent: null, bar: "hidden", visible: true,
    };
  }
  return {
    state: "idle", title: "", detail: "", percent: null, bar: "hidden", visible: false,
  };
}
