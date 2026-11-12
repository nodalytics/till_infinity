"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { candles, chrome, palette } from "@/lib/chart";
import { bands, mean, volatility } from "@/lib/indicators";
import { addLine, dropLine, lines } from "@/lib/draw";
import { stamp } from "@/lib/format";
import type { Chart as ChartData } from "@/lib/types";

export interface Toggles {
  markers: boolean;
  refusals: boolean;
  levels: boolean;
  ma: boolean;
  bands: boolean;
  vol: boolean;
  drawing: boolean;
}

interface Readout {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** What the desk did on this candle, if anything. */
  notes: string[];
}

interface Measure {
  from: { x: number; y: number; price: number; index: number };
  to: { x: number; y: number; price: number; index: number } | null;
}

/**
 * The candles, the desk's own overlays, and the two interactions worth having.
 *
 * What a generic charting page cannot draw is here: the levels the desk traded
 * or was refused at, and the refusals themselves - a gate saying no leaves no
 * order and no fill, so the journal's observation is the only record that the
 * desk wanted something at that price and did not get it.
 *
 * Everything derived is labelled. A desk level is a dashed line in the signal
 * colour with `desk` in its label; a line the viewer placed is solid, in the
 * accent, labelled `drawn`. Nobody should have to guess which is a measurement.
 */
export default function Chart({
  data,
  theme,
  toggles,
  onPrice,
}: {
  data: ChartData;
  theme: string;
  toggles: Toggles;
  onPrice?: (price: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const price = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const fast = useRef<ISeriesApi<"Line"> | null>(null);
  const slow = useRef<ISeriesApi<"Line"> | null>(null);
  const upper = useRef<ISeriesApi<"Line"> | null>(null);
  const lower = useRef<ISeriesApi<"Line"> | null>(null);
  const vol = useRef<ISeriesApi<"Line"> | null>(null);
  const pins = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const drawnLines = useRef<IPriceLine[]>([]);
  const deskLines = useRef<IPriceLine[]>([]);

  const [readout, setReadout] = useState<Readout | null>(null);
  const [drawn, setDrawn] = useState<number[]>([]);
  const [measure, setMeasure] = useState<Measure | null>(null);

  useEffect(() => setDrawn(lines(data.feed)), [data.feed]);

  // ---- create once -------------------------------------------------------
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const tones = palette();
    const api = createChart(element, {
      ...chrome(tones),
      width: element.clientWidth,
      height: element.clientHeight,
    });
    chart.current = api;
    price.current = api.addSeries(CandlestickSeries, candles(tones));
    pins.current = createSeriesMarkers(price.current, []);

    const thin = { lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false };
    fast.current = api.addSeries(LineSeries, { ...thin, color: tones["--accent"] });
    slow.current = api.addSeries(LineSeries, { ...thin, color: tones["--ink-3"] });
    upper.current = api.addSeries(LineSeries, {
      ...thin,
      color: tones["--ink-3"],
      lineStyle: LineStyle.Dashed,
    });
    lower.current = api.addSeries(LineSeries, {
      ...thin,
      color: tones["--ink-3"],
      lineStyle: LineStyle.Dashed,
    });
    // Its own scale, pinned to the bottom fifth, so a bps figure never shares
    // an axis with a price and squash the candles into a band.
    vol.current = api.addSeries(LineSeries, {
      ...thin,
      color: tones["--signal-fill"],
      priceScaleId: "vol",
    });
    api.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });

    const observer = new ResizeObserver(() =>
      api.applyOptions({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      api.remove();
      chart.current = null;
      price.current = null;
      pins.current = null;
      drawnLines.current = [];
      deskLines.current = [];
    };
  }, []);

  // ---- follow the theme --------------------------------------------------
  useEffect(() => {
    const api = chart.current;
    if (!api) return;
    const tones = palette();
    api.applyOptions(chrome(tones));
    price.current?.applyOptions(candles(tones));
    fast.current?.applyOptions({ color: tones["--accent"] });
    slow.current?.applyOptions({ color: tones["--ink-3"] });
    upper.current?.applyOptions({ color: tones["--ink-3"] });
    lower.current?.applyOptions({ color: tones["--ink-3"] });
    vol.current?.applyOptions({ color: tones["--signal-fill"] });
  }, [theme]);

  // ---- candles, markers, indicators -------------------------------------
  useEffect(() => {
    const series = price.current;
    if (!series) return;
    const tones = palette();
    const rows: CandlestickData<UTCTimestamp>[] = data.bars.map((bar) => ({
      time: bar.time as UTCTimestamp,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    series.setData(rows);

    const pinned: SeriesMarker<Time>[] = [];
    if (toggles.markers) {
      for (const [index, marker] of data.markers.entries()) {
        const entry = marker.kind === "entry";
        const short = marker.side === "sell";
        pinned.push({
          id: `t${index}`,
          time: marker.time as UTCTimestamp,
          position: entry ? (short ? "atPriceTop" : "atPriceBottom") : "atPriceMiddle",
          price: marker.price,
          shape: entry ? (short ? "arrowDown" : "arrowUp") : "circle",
          color: entry
            ? short
              ? tones["--down"]
              : tones["--up"]
            : marker.r >= 0
              ? tones["--up"]
              : tones["--down"],
          // No text on the marker itself. Twenty-four of them in one pane
          // overlap into an unreadable smear, and the crosshair readout below
          // names the rule, the R and the reason for whatever bar is under the
          // pointer - which is the question a label was trying to answer.
          text: "",
          size: entry ? 1.1 : 0.8,
        });
      }
    }
    if (toggles.refusals) {
      for (const [index, mark] of data.refusals.entries()) {
        if (mark.price == null) continue;
        pinned.push({
          id: `r${index}`,
          time: mark.time as UTCTimestamp,
          position: "atPriceMiddle",
          price: mark.price,
          shape: "square",
          color: tones["--signal-fill"],
          text: "",
          size: 0.6,
        });
      }
    }
    pinned.sort((a, b) => Number(a.time) - Number(b.time));
    pins.current?.setMarkers(pinned);

    fast.current?.setData(
      toggles.ma
        ? mean(data.bars, 20).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }))
        : [],
    );
    slow.current?.setData(
      toggles.ma
        ? mean(data.bars, 50).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }))
        : [],
    );
    const band = toggles.bands ? bands(data.bars) : [];
    upper.current?.setData(band.map((p) => ({ time: p.time as UTCTimestamp, value: p.upper })));
    lower.current?.setData(band.map((p) => ({ time: p.time as UTCTimestamp, value: p.lower })));
    vol.current?.setData(
      toggles.vol
        ? volatility(data.bars).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }))
        : [],
    );

    chart.current?.timeScale().fitContent();
  }, [data, toggles]);

  // ---- the desk's own levels --------------------------------------------
  useEffect(() => {
    const series = price.current;
    if (!series) return;
    for (const line of deskLines.current) series.removePriceLine(line);
    deskLines.current = [];
    if (!toggles.levels) return;
    const tones = palette();
    for (const level of data.levels.slice(0, 40)) {
      deskLines.current.push(
        series.createPriceLine({
          price: level.price,
          color: tones["--signal-fill"],
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: false,
          title: `desk ${level.traded ? `${level.traded}t` : ""}${level.refused ? `${level.refused}r` : ""}`,
        }),
      );
    }
  }, [data, toggles.levels, theme]);

  // ---- lines the viewer placed ------------------------------------------
  useEffect(() => {
    const series = price.current;
    if (!series) return;
    for (const line of drawnLines.current) series.removePriceLine(line);
    const tones = palette();
    drawnLines.current = drawn.map((value) =>
      series.createPriceLine({
        price: value,
        color: tones["--accent"],
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: "drawn",
      }),
    );
  }, [drawn, theme]);

  // ---- crosshair readout -------------------------------------------------
  useEffect(() => {
    const api = chart.current;
    const series = price.current;
    if (!api || !series) return;
    const handler = (param: MouseEventParams) => {
      const bar = param.seriesData.get(series) as CandlestickData<UTCTimestamp> | undefined;
      if (!bar || param.time == null) {
        setReadout(null);
        return;
      }
      const when = Number(param.time);
      // Markers are snapped to their bar by the API, so an exact match is the
      // right test: whatever happened on this candle, named in full.
      const notes = [
        ...data.markers
          .filter((mark) => mark.time === when)
          .map((mark) =>
            mark.kind === "entry"
              ? `${mark.side} ${mark.strategy}`
              : `exit ${mark.label}`,
          ),
        ...data.refusals
          .filter((mark) => mark.time === when)
          .map((mark) => `refused: ${mark.why || mark.gate}`),
      ];
      setReadout({ time: when, open: bar.open, high: bar.high, low: bar.low, close: bar.close, notes });
    };
    api.subscribeCrosshairMove(handler);
    return () => api.unsubscribeCrosshairMove(handler);
  }, [data]);

  // ---- measure, and placing a line --------------------------------------
  const priceAt = useCallback((y: number) => price.current?.coordinateToPrice(y) ?? null, []);
  const indexAt = useCallback(
    (x: number) => chart.current?.timeScale().coordinateToLogical(x) ?? null,
    [],
  );

  const down = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const box = host.current?.getBoundingClientRect();
    if (!box) return;
    const x = event.clientX - box.left;
    const y = event.clientY - box.top;
    const at = priceAt(y);
    if (at == null) return;

    if (toggles.drawing) {
      setDrawn(addLine(data.feed, Number(at)));
      onPrice?.(Number(at));
      return;
    }
    // Shift-drag measures. A plain drag stays the chart's own pan, which is
    // the gesture people use far more often.
    if (!event.shiftKey) return;
    event.preventDefault();
    setMeasure({ from: { x, y, price: Number(at), index: Number(indexAt(x) ?? 0) }, to: null });
  };

  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!measure) return;
    const box = host.current?.getBoundingClientRect();
    if (!box) return;
    const x = event.clientX - box.left;
    const y = event.clientY - box.top;
    const at = priceAt(y);
    if (at == null) return;
    setMeasure({
      ...measure,
      to: { x, y, price: Number(at), index: Number(indexAt(x) ?? 0) },
    });
  };

  const up = () => {
    if (measure && !measure.to) setMeasure(null);
  };

  const tag = measure?.to
    ? (() => {
        const delta = measure.to.price - measure.from.price;
        const share = measure.from.price ? (delta / measure.from.price) * 100 : 0;
        const count = Math.abs(Math.round(measure.to.index - measure.from.index));
        return `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toPrecision(5)}  ${share >= 0 ? "+" : "−"}${Math.abs(share).toFixed(2)}%  ${count} bars`;
      })()
    : null;

  return (
    <div
      ref={host}
      className="canvas"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerLeave={up}
      style={{ cursor: toggles.drawing ? "crosshair" : undefined }}
    >
      {readout && (
        <div className="readout">
          <b>{data.feed}</b>
          <span>{data.interval}</span>
          <span className="dim">{stamp(readout.time)}</span>
          <span>
            O <b>{readout.open}</b>
          </span>
          <span>
            H <b>{readout.high}</b>
          </span>
          <span>
            L <b>{readout.low}</b>
          </span>
          <span className={readout.close >= readout.open ? "up" : "down"}>
            C <b>{readout.close}</b>
          </span>
          {readout.notes.map((note, index) => (
            <span key={index} className={note.startsWith("refused") ? "warn" : undefined}>
              {note}
            </span>
          ))}
        </div>
      )}

      {drawn.length > 0 && (
        <div className="drawn">
          {drawn.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setDrawn(dropLine(data.feed, value))}
              title="Remove this line"
            >
              {value.toPrecision(7)} &times;
            </button>
          ))}
        </div>
      )}

      {measure?.to && (
        <>
          <div
            className="measure"
            style={{
              left: Math.min(measure.from.x, measure.to.x),
              top: Math.min(measure.from.y, measure.to.y),
              width: Math.abs(measure.to.x - measure.from.x),
              height: Math.abs(measure.to.y - measure.from.y),
            }}
          />
          <div className="measure-tag" style={{ left: measure.to.x + 8, top: measure.to.y - 10 }}>
            {tag}
          </div>
        </>
      )}

      <div className="chart-hint">
        {toggles.drawing ? (
          <span className="warn">click to place a line</span>
        ) : (
          <span className="dim">shift-drag to measure</span>
        )}
      </div>
    </div>
  );
}

