"use client";

import { useEffect, useRef } from "react";
import {
  BaselineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { chrome, palette } from "@/lib/chart";
import type { EquityPoint } from "@/lib/types";

/**
 * Cumulative realised R, or money, after each closed trade.
 *
 * A baseline series rather than a line, so the curve is green above zero and
 * red below without a legend saying so. Zero is the only interesting level on
 * a cumulative-R curve: above it the account is up on its own risk, below it
 * the desk has paid to be in the market.
 */
export default function Equity({
  points,
  unit,
  theme,
}: {
  points: EquityPoint[];
  unit: "r" | "money";
  theme: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);
  const zero = useRef<ReturnType<ISeriesApi<"Baseline">["createPriceLine"]> | null>(null);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const api = createChart(element, {
      ...chrome(palette(), { rightOffset: 2 }),
      width: element.clientWidth,
      height: element.clientHeight,
    });
    chart.current = api;
    series.current = api.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerRadius: 3,
    });

    const observer = new ResizeObserver(() =>
      api.applyOptions({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      api.remove();
      chart.current = null;
      series.current = null;
      zero.current = null;
    };
  }, []);

  useEffect(() => {
    const line = series.current;
    const api = chart.current;
    if (!line || !api) return;
    const tones = palette();
    api.applyOptions(chrome(tones, { rightOffset: 2 }));
    line.applyOptions({
      topLineColor: tones["--up"],
      topFillColor1: `${tones["--up"]}55`,
      topFillColor2: `${tones["--up"]}08`,
      bottomLineColor: tones["--down"],
      bottomFillColor1: `${tones["--down"]}08`,
      bottomFillColor2: `${tones["--down"]}55`,
      priceFormat: { type: "price", precision: unit === "r" ? 2 : 0, minMove: 0.01 },
    });
    if (zero.current) line.removePriceLine(zero.current);
    zero.current = line.createPriceLine({
      price: 0,
      color: tones["--rule"],
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: false,
    });
  }, [theme, unit]);

  useEffect(() => {
    const line = series.current;
    if (!line) return;
    // Times have to be strictly ascending whole seconds. Two trades can close
    // in the same second and the journal records fractional ones, so a
    // duplicate is nudged a second later rather than dropped - a dropped point
    // silently flattens a step in the curve.
    let last = -Infinity;
    line.setData(
      points.map((point) => {
        const time = Math.max(Math.floor(point.time), last + 1);
        last = time;
        return {
          time: time as UTCTimestamp,
          value: unit === "r" ? point.cumulative_r : point.cumulative_profit,
        };
      }),
    );
    chart.current?.timeScale().fitContent();
  }, [points, unit]);

  return <div ref={host} style={{ width: "100%", height: 150 }} />;
}
