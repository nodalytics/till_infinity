/**
 * One chart theme, read from the stylesheet rather than repeated here.
 *
 * `globals.css` owns the palette - measured off the live charting site - and
 * this asks the document for it, so a chart never ends up on the old colours
 * after a theme change. The fallbacks are the same values and only matter in
 * a renderer with no stylesheet attached.
 */

import { ColorType, CrosshairMode, type ChartOptions, type DeepPartial } from "lightweight-charts";

// Literal keys, so a token missing from the stylesheet is a type error here
// rather than an undefined colour that paints as black on black.
const FALLBACK = {
  "--chart-bg": "#131722",
  "--panel": "#1e222d",
  "--rule": "#2a2e39",
  "--grid": "#2b2b43",
  "--ink": "#d1d4dc",
  "--ink-2": "#b2b5be",
  "--ink-3": "#787b86",
  "--up": "#089981",
  "--down": "#f23645",
  "--up-ink": "#089981",
  "--down-ink": "#f23645",
  "--wick": "#737375",
  "--accent": "#4d8aff",
  "--signal": "#e3b341",
  "--signal-fill": "#e3b341",
  "--alarm": "#ff6b5e",
} satisfies Record<string, string>;

export type Palette = { [K in keyof typeof FALLBACK]: string };

export function palette(): Palette {
  if (typeof window === "undefined") return { ...FALLBACK } as Palette;
  const computed = getComputedStyle(document.documentElement);
  const out: Record<string, string> = {};
  for (const [name, fallback] of Object.entries(FALLBACK)) {
    out[name] = computed.getPropertyValue(name).trim() || fallback;
  }
  return out as Palette;
}

/**
 * Chart chrome. The grid, scale border and crosshair follow the theme.
 *
 * Horizontal grid lines only: the time axis is already ruled by the panel
 * edges, and the library's own default draws both, which at this density
 * reads as graph paper behind the candles.
 */
export function chrome(
  tones: Palette,
  opts: { rightOffset?: number } = {},
): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: tones["--chart-bg"] },
      textColor: tones["--ink-3"],
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: tones["--grid"] },
    },
    rightPriceScale: {
      borderColor: tones["--rule"],
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: tones["--rule"],
      timeVisible: true,
      secondsVisible: false,
      rightOffset: opts.rightOffset ?? 6,
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: tones["--ink-3"],
        width: 1,
        style: 3,
        labelBackgroundColor: tones["--panel"],
      },
      horzLine: {
        color: tones["--ink-3"],
        width: 1,
        style: 3,
        labelBackgroundColor: tones["--panel"],
      },
    },
    handleScale: { axisPressedMouseMove: { price: false } },
    autoSize: false,
  };
}

/** Candle colours, as the site draws them. */
export function candles(tones: Palette) {
  return {
    upColor: tones["--up"],
    downColor: tones["--down"],
    borderUpColor: tones["--up"],
    borderDownColor: tones["--down"],
    wickUpColor: tones["--wick"],
    wickDownColor: tones["--wick"],
    priceLineVisible: false,
    lastValueVisible: false,
  };
}
