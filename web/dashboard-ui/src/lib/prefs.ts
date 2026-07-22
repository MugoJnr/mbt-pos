/** Persisted Live Dashboard preferences (localStorage). */

export type TableDensity = "comfortable" | "compact";
export type DashLanguage = "en" | "sw";

export type DashboardPrefs = {
  refreshIntervalSec: number;
  notificationsEnabled: boolean;
  showCharts: boolean;
  showWidgets: boolean;
  tableDensity: TableDensity;
  language: DashLanguage;
  exportFormat: "csv" | "xlsx";
  layout: "auto" | "dense" | "relaxed";
  widgets: {
    paymentMix: boolean;
    bestSellers: boolean;
    topCategories: boolean;
    activity: boolean;
    quickActions: boolean;
    health: boolean;
  };
};

const KEY = "mbt-dash-prefs";

export const DEFAULT_PREFS: DashboardPrefs = {
  refreshIntervalSec: 45,
  notificationsEnabled: true,
  showCharts: true,
  showWidgets: true,
  tableDensity: "comfortable",
  language: "en",
  exportFormat: "csv",
  layout: "auto",
  widgets: {
    paymentMix: true,
    bestSellers: true,
    topCategories: true,
    activity: true,
    quickActions: true,
    health: true,
  },
};

export function loadPrefs(): DashboardPrefs {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT_PREFS, widgets: { ...DEFAULT_PREFS.widgets } };
    const parsed = JSON.parse(raw) as Partial<DashboardPrefs>;
    return {
      ...DEFAULT_PREFS,
      ...parsed,
      widgets: { ...DEFAULT_PREFS.widgets, ...(parsed.widgets || {}) },
    };
  } catch {
    return { ...DEFAULT_PREFS, widgets: { ...DEFAULT_PREFS.widgets } };
  }
}

export function savePrefs(prefs: DashboardPrefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
    window.dispatchEvent(new CustomEvent("mbt-prefs-changed", { detail: prefs }));
  } catch {
    /* ignore quota */
  }
}

export function prefsRefreshMs(prefs?: DashboardPrefs): number {
  const sec = Math.max(15, Number((prefs || loadPrefs()).refreshIntervalSec) || 45);
  return sec * 1000;
}
