export type ServedDashboard = {
  version?: string;
  build?: string;
  entry_script?: string;
  asset_ready?: boolean;
};

export type ReleaseSnap = {
  served: ServedDashboard | null;
  failed: boolean;
  mismatch: boolean;
  phase: "idle" | "working" | "failed";
  message: string;
  verified: string;
  percent: number | null;
};

const listeners = new Set<() => void>();
let started = false;
let unsaved = false;
let snap: ReleaseSnap = {
  served: null,
  failed: false,
  mismatch: false,
  phase: "idle",
  message: "",
  verified: "",
  percent: null,
};

function publish(next: Partial<ReleaseSnap>) {
  snap = { ...snap, ...next };
  listeners.forEach((listener) => listener());
}

export function loadedDashboardScript(): string {
  const node = document.querySelector('script[type="module"][src*="/assets/"]') as HTMLScriptElement | null;
  if (!node) return "";
  try {
    return new URL(node.src, window.location.origin).pathname;
  } catch {
    return node.getAttribute("src") || "";
  }
}

export function browserDashboardVersion(): string {
  try {
    return typeof __MBT_DASHBOARD_VERSION__ === "string" ? __MBT_DASHBOARD_VERSION__ : "";
  } catch {
    return "";
  }
}

export function scriptIdentity(value: string): string {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const withoutHash = raw.split("#")[0];
  try {
    const url = new URL(withoutHash, "http://dashboard.local");
    const name = url.pathname.split("/").filter(Boolean).pop() || "";
    return name.split("?")[0];
  } catch {
    const path = withoutHash.split("?")[0];
    return path.split("/").filter(Boolean).pop() || "";
  }
}

export function scriptsMatch(loaded: string, served: string): boolean {
  const left = scriptIdentity(loaded);
  const right = scriptIdentity(served);
  return Boolean(left) && left === right;
}

export function dashboardMismatch(loadedScript: string, _browserVersion: string, served: ServedDashboard | null): boolean {
  // The version string baked into a bundle cannot change when that same file
  // is loaded again. The served file name is the only refresh signal.
  if (!served) return false;
  const expected = served.entry_script || "";
  if (expected && loadedScript && scriptsMatch(loadedScript, expected)) return false;
  if (served.asset_ready === false && expected) return true;
  return Boolean(expected) && Boolean(loadedScript) && !scriptsMatch(loadedScript, expected);
}

export function releaseNeedsRefresh(
  loadedScript: string,
  browserVersion: string,
  served: ServedDashboard | null,
  pendingEntry = "",
): { show: boolean; landed: boolean; missed: boolean } {
  const mismatch = dashboardMismatch(loadedScript, browserVersion, served);
  const missed = Boolean(pendingEntry) && !scriptsMatch(loadedScript, pendingEntry);
  const landed = Boolean(pendingEntry) && scriptsMatch(loadedScript, pendingEntry) && !mismatch;
  return { show: mismatch || missed, landed, missed };
}

async function readServed(): Promise<ServedDashboard> {
  const response = await fetch("/api/dashboard-version", { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function readPendingRefresh(): { entry?: string; version?: string } | null {
  const raw = sessionStorage.getItem("mbt-dashboard-refresh");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    sessionStorage.removeItem("mbt-dashboard-refresh");
    return null;
  }
}

function clearRefreshMarker() {
  sessionStorage.removeItem("mbt-dashboard-refresh");
  const url = new URL(window.location.href);
  if (!url.searchParams.has("dashboard")) return;
  url.searchParams.delete("dashboard");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

async function check() {
  try {
    const served = await readServed();
    const loaded = loadedDashboardScript();
    const pending = readPendingRefresh();
    const decision = releaseNeedsRefresh(
      loaded,
      browserDashboardVersion(),
      served,
      pending?.entry || "",
    );
    const pendingMissed = decision.missed;
    const refreshLanded = decision.landed;
    if (pending && !pendingMissed) clearRefreshMarker();
    const showButton = decision.show;
    publish({
      served,
      failed: false,
      mismatch: showButton,
      phase: pendingMissed ? "failed" : "idle",
      percent: null,
      verified: refreshLanded
        ? `Dashboard updated to v${pending?.version || served.version || browserDashboardVersion() || "current"}`
        : "",
      message: pendingMissed
        ? "The refresh did not load the served dashboard. Try again."
        : (served.asset_ready === false ? "The served dashboard is missing its script." : ""),
    });
  } catch {
    publish({ served: null, failed: true, mismatch: false, verified: "", message: "" });
  }
}

export function startDashboardReleaseCheck() {
  if (started || typeof window === "undefined") return;
  started = true;
  window.addEventListener("mbt-unsaved", ((event: CustomEvent<boolean>) => {
    unsaved = Boolean(event.detail);
  }) as EventListener);
  void check();
  window.setInterval(() => void check(), 45_000);
  window.addEventListener("focus", () => void check());
}

export function subscribeDashboardRelease(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getDashboardRelease(): ReleaseSnap {
  return snap;
}

async function fetchFreshAsset(url: string): Promise<void> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  const total = Number(response.headers.get("content-length") || 0);
  if (!response.body || total <= 0) {
    await response.arrayBuffer();
    return;
  }
  const reader = response.body.getReader();
  let got = 0;
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    got += step.value.byteLength;
    publish({ percent: Math.min(99, Math.floor((got * 100) / total)) });
  }
}

export async function refreshToLatestVersion() {
  publish({ phase: "working", percent: null, message: "Refreshing dashboard…", verified: "" });
  let served: ServedDashboard;
  try {
    served = await readServed();
  } catch {
    publish({
      phase: "failed",
      failed: true,
      percent: null,
      message: "Could not check the dashboard version. The page was not changed.",
    });
    return;
  }
  if (served.asset_ready === false) {
    publish({
      phase: "failed",
      served,
      mismatch: true,
      percent: null,
      message: "The served dashboard is missing its script. Retry when the update has finished.",
    });
    return;
  }
  if (unsaved && !window.confirm("This page has an unfinished sale. Refreshing will leave it. Continue?")) {
    publish({ phase: "idle", percent: null });
    return;
  }
  try {
    const page = await fetch(`${window.location.pathname}${window.location.search}`, { cache: "no-store" });
    const html = await page.text();
    const match = html.match(/src="(\/assets\/[^"]+\.js)"/);
    const entry = match?.[1] || served.entry_script || "";
    if (entry) await fetchFreshAsset(entry);
  } catch {
    publish({
      phase: "failed",
      mismatch: true,
      percent: null,
      message: "The latest dashboard could not be downloaded. Try again.",
    });
    return;
  }
  sessionStorage.setItem("mbt-dashboard-refresh", JSON.stringify({
    entry: served.entry_script || "",
    version: served.version || "",
    build: served.build || "",
  }));
  const url = new URL(window.location.href);
  url.searchParams.set("dashboard", served.build || served.version || "latest");
  window.location.replace(url.toString());
}
