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

/** How long `.theming` stays on. Matches `--t-mid` in `globals.css`. */
const CROSSFADE = 200;

let settle: number | null = null;

/**
 * Apply a theme, with the surfaces crossfading rather than cutting.
 *
 * `.theming` turns on a colour transition for every element for the length of
 * the flip and then takes it off again. It is deliberately not permanent: a
 * standing `* { transition: color }` makes every hover in the app lag by the
 * same amount.
 *
 * **Respects the viewer's setting without asking the stylesheet to.** The
 * reduced-motion media query in `globals.css` already collapses the duration,
 * but adding and removing a class on `<html>` 200ms apart is a DOM write
 * either way, so it is skipped outright here.
 */
export function crossfade(theme: Theme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  let still = false;
  try {
    still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    still = false;
  }
  if (still) {
    apply(theme);
    return;
  }
  root.classList.add("theming");
  apply(theme);
  if (settle != null) window.clearTimeout(settle);
  settle = window.setTimeout(() => {
    root.classList.remove("theming");
    settle = null;
  }, CROSSFADE);
}
