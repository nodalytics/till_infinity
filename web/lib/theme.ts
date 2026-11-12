/**
 * Light or dark, chosen by the person or by their system.
 *
 * Every `localStorage` call is wrapped: in a private window, with site data
 * blocked, or inside a screenshot runner, the accessor throws rather than
 * returning null. The page has to render correctly when that happens, so a
 * failed read is simply "no choice recorded" and a failed write is simply "not
 * remembered" - neither is an error worth showing anybody.
 */

export type Theme = "light" | "dark";

export const KEY = "till-infinity.theme";

/** The inline script that runs before first paint. Keep it in sync with the
 *  functions below; it exists because resolving the theme in an effect paints
 *  the wrong one first and then corrects it, which is a visible flash. */
export const BOOT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(KEY)});if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}document.documentElement.setAttribute("data-theme",t);}catch(e){document.documentElement.setAttribute("data-theme","dark");}})();`;

export function stored(): Theme | null {
  try {
    const found = localStorage.getItem(KEY);
    return found === "light" || found === "dark" ? found : null;
  } catch {
    return null;
  }
}

export function remember(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Not remembered. The page still works; the next load asks the system.
  }
}

export function forget(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Same: nothing to do and nothing worth reporting.
  }
}

export function system(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "dark";
  }
}

/** What the document is actually showing, which the boot script has set. */
export function current(): Theme {
  if (typeof document === "undefined") return "dark";
  const found = document.documentElement.getAttribute("data-theme");
  return found === "light" ? "light" : found === "dark" ? "dark" : system();
}

export function apply(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}
