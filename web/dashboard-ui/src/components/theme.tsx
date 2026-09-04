import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "dark" | "light";
/** "system" follows the OS until the operator picks a side explicitly. */
export type ThemeMode = Theme | "system";
/** Optional visual variants — CSS tokens live under [data-variant]. Toggle stays dark/light. */
export type ThemeVariant = "default" | "mugobyte" | "retail" | "minimal" | "contrast";

const THEME_KEY = "mbt-theme";
const VARIANT_KEY = "mbt-variant";
const VARIANTS: ThemeVariant[] = ["default", "mugobyte", "retail", "minimal", "contrast"];
const MODE_ORDER: ThemeMode[] = ["system", "light", "dark"];

const ThemeCtx = createContext<{
  /** Resolved appearance actually painted. */
  theme: Theme;
  /** Stored preference, including "system". */
  mode: ThemeMode;
  variant: ThemeVariant;
  toggle: () => void;
  cycle: () => void;
  set: (t: ThemeMode) => void;
  setVariant: (v: ThemeVariant) => void;
}>({
  theme: "dark",
  mode: "system",
  variant: "default",
  toggle: () => {},
  cycle: () => {},
  set: () => {},
  setVariant: () => {},
});

function prefersLight() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: light)").matches;
}

function readMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light" || saved === "system") return saved;
  } catch {
    /* private mode — fall through to the OS preference */
  }
  return "system";
}

function resolve(mode: ThemeMode): Theme {
  if (mode === "system") return prefersLight() ? "light" : "dark";
  return mode;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readMode);
  const [theme, setTheme] = useState<Theme>(() => resolve(readMode()));
  const [variant, setVariant] = useState<ThemeVariant>("default");

  useEffect(() => {
    setMode(readMode());
    try {
      const v = localStorage.getItem(VARIANT_KEY) as ThemeVariant | null;
      if (v && VARIANTS.includes(v)) setVariant(v);
    } catch {
      /* ignore */
    }
  }, []);

  // Follow the OS while no explicit side has been chosen.
  useEffect(() => {
    setTheme(resolve(mode));
    if (mode !== "system" || typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => setTheme(prefersLight() ? "light" : "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(theme);
    root.style.colorScheme = theme;
    root.dataset.themeMode = mode;
    if (variant === "default") {
      root.removeAttribute("data-variant");
    } else {
      root.setAttribute("data-variant", variant);
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#F8FAFC" : "#0B1220");
    try {
      localStorage.setItem(THEME_KEY, mode);
      localStorage.setItem(VARIANT_KEY, variant);
    } catch {
      /* ignore */
    }
  }, [theme, mode, variant]);

  const set = useCallback((t: ThemeMode) => setMode(t), []);
  const toggle = useCallback(() => setMode(resolve(readMode()) === "dark" ? "light" : "dark"), []);
  const cycle = useCallback(
    () => setMode((m) => MODE_ORDER[(MODE_ORDER.indexOf(m) + 1) % MODE_ORDER.length]),
    [],
  );

  const value = useMemo(
    () => ({ theme, mode, variant, set, setVariant, toggle, cycle }),
    [theme, mode, variant, set, toggle, cycle],
  );

  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
