export type Theme = "dark" | "light";

const stored = (): Theme | null => {
  try {
    const value = window.localStorage?.getItem("m87-console-theme");
    return value === "dark" || value === "light" ? value : null;
  } catch {
    return null;
  }
};

export const currentTheme = (): Theme =>
  stored() ?? (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");

export const applyTheme = (theme: Theme) => {
  document.documentElement.dataset.theme = theme;
};

export const applyStoredTheme = () => applyTheme(currentTheme());

export const saveTheme = (theme: Theme) => {
  try {
    window.localStorage?.setItem("m87-console-theme", theme);
  } catch {
    /* The choice still applies until the page reloads. */
  }
  applyTheme(theme);
};
