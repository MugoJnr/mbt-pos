import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "dark" | "light";
/** Optional visual variants — CSS tokens live under [data-variant]. Toggle stays dark/light. */
export type ThemeVariant = "default" | "mugobyte" | "retail" | "minimal" | "contrast";

const ThemeCtx = createContext<{
  theme: Theme;
  variant: ThemeVariant;
  toggle: () => void;
  set: (t: Theme) => void;
  setVariant: (v: ThemeVariant) => void;
}>({
  theme: "dark",
  variant: "default",
  toggle: () => {},
  set: () => {},
  setVariant: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [variant, setVariant] = useState<ThemeVariant>("default");

  useEffect(() => {
    const saved = (typeof window !== "undefined" && localStorage.getItem("mbt-theme")) as Theme | null;
    if (saved === "dark" || saved === "light") setTheme(saved);
    const v = (typeof window !== "undefined" && localStorage.getItem("mbt-variant")) as ThemeVariant | null;
    if (v && ["default", "mugobyte", "retail", "minimal", "contrast"].includes(v)) {
      setVariant(v);
    }
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(theme);
    root.style.colorScheme = theme;
    if (variant === "default") {
      root.removeAttribute("data-variant");
    } else {
      root.setAttribute("data-variant", variant);
    }
    try {
      localStorage.setItem("mbt-theme", theme);
      localStorage.setItem("mbt-variant", variant);
    } catch {}
  }, [theme, variant]);

  return (
    <ThemeCtx.Provider
      value={{
        theme,
        variant,
        set: setTheme,
        setVariant,
        toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
      }}
    >
      {children}
    </ThemeCtx.Provider>
  );
}

export const useTheme = () => useContext(ThemeCtx);
