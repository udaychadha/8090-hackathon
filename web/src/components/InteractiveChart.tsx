import { useEffect, useId, useRef, useState } from "react";
import type { PointerEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import { formatNumber } from "../evidence";

export interface ChartPoint {
  time: number;
  date: string;
  label: string;
  values: number[];
  details: [string, string][];
  volume?: number;
}
export interface ChartModel {
  title: string;
  kind: "equity" | "dataset";
  points: ChartPoint[];
  series: { label: string; className: string }[];
  primary: number;
  isEnd: string | null;
  caption: string;
}

function nearest(points: ChartPoint[], time: number) {
  let low = 0,
    high = points.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (points[mid].time < time) low = mid + 1;
    else high = mid;
  }
  return low > 0 && time - points[low - 1].time <= points[low].time - time
    ? low - 1
    : low;
}

function Plot({
  model,
  expanded = false,
}: {
  model: ChartModel;
  expanded?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 960, height: 360 });
  const [selected, setSelected] = useState<number | null>(null);
  const helpId = useId();
  useEffect(() => {
    const element = host.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      if (width > 0 && height > 0) setSize({ width, height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const { points } = model;
  const values = points.flatMap((p) => p.values);
  const low = Math.min(...values),
    high = Math.max(...values);
  const padding = (high - low) * 0.08 || Math.max(Math.abs(low) * 0.02, 0.01);
  const left = 58,
    right = size.width - 24,
    top = 32;
  const bottom = size.height - (model.kind === "dataset" ? 80 : 45);
  const start = points[0].time,
    end = points.at(-1)!.time;
  const x = (time: number) =>
    end === start
      ? (left + right) / 2
      : left + ((time - start) / (end - start)) * (right - left);
  const y = (value: number) =>
    bottom -
    ((value - low + padding) / (high - low + 2 * padding)) * (bottom - top);
  const active = selected == null ? null : points[selected];
  const cursorX = active ? x(active.time) : 0;
  const cursorY = active ? y(active.values[model.primary]) : 0;
  const tooltipWidth = Math.min(280, size.width - 24);
  const tooltipLeft = Math.max(
    12,
    Math.min(
      size.width - tooltipWidth - 12,
      cursorX > size.width / 2 ? cursorX - tooltipWidth - 16 : cursorX + 16,
    ),
  );
  const boundaryTime = model.isEnd ? Date.parse(model.isEnd) : NaN;
  const boundary = x(boundaryTime);
  const maxVolume = Math.max(1, ...points.map((p) => p.volume ?? 0));
  const inspect = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const px = ((event.clientX - box.left) * size.width) / box.width;
    const py = ((event.clientY - box.top) * size.height) / box.height;
    if (px < left || px > right || py < top || py > size.height - 25) {
      setSelected(null);
      return;
    }
    setSelected(
      nearest(points, start + ((px - left) / (right - left)) * (end - start)),
    );
  };
  const selectedText = active
    ? [
        active.label,
        ...active.details.map(([key, value]) => `${key}: ${value}`),
      ].join(". ")
    : "Use arrow keys to inspect recorded points";
  return (
    <>
      <div className="chart-plot">
        <div
          ref={host}
          className={`chart-canvas ${model.kind}-canvas${expanded ? " chart-canvas-expanded" : ""}`}
        >
          <svg
            className="chart interactive-chart"
            viewBox={`0 0 ${size.width} ${size.height}`}
            role="slider"
            aria-label={
              model.kind === "equity" ? "Equity chart" : "Dataset price chart"
            }
            aria-valuemin={0}
            aria-valuemax={points.length - 1}
            aria-valuenow={selected ?? 0}
            aria-valuetext={selectedText}
            aria-describedby={helpId}
            tabIndex={0}
            onFocus={() => setSelected((current) => current ?? 0)}
            onBlur={() => setSelected(null)}
            onPointerMove={inspect}
            onPointerDown={(event) => {
              event.currentTarget.focus({ preventScroll: true });
              inspect(event);
            }}
            onPointerLeave={(event) => {
              if (event.pointerType !== "touch") setSelected(null);
            }}
            onPointerCancel={() => setSelected(null)}
            onKeyDown={(event) => {
              let next: number;
              if (event.key === "Home") next = 0;
              else if (event.key === "End") next = points.length - 1;
              else if (["ArrowLeft", "ArrowDown"].includes(event.key))
                next = (selected ?? 0) - 1;
              else if (["ArrowRight", "ArrowUp"].includes(event.key))
                next = (selected ?? 0) + 1;
              else return;
              event.preventDefault();
              setSelected(Math.max(0, Math.min(points.length - 1, next)));
            }}
          >
            <title>{model.title} · recorded observations only</title>
            {[0, 0.25, 0.5, 0.75, 1].map((t) => {
              const value = low - padding + t * (high - low + padding * 2);
              return (
                <g key={t} aria-hidden="true">
                  <line
                    className="gridline"
                    x1={left}
                    x2={right}
                    y1={y(value)}
                    y2={y(value)}
                  />
                  <text x={left - 8} y={y(value) + 4} textAnchor="end">
                    {formatNumber(value, high - low < 0.05 ? 4 : 2)}
                  </text>
                </g>
              );
            })}
            {Number.isFinite(boundaryTime) &&
              boundaryTime >= start &&
              boundaryTime <= end && (
                <g aria-hidden="true">
                  <line
                    className="boundary"
                    x1={boundary}
                    x2={boundary}
                    y1={top}
                    y2={bottom}
                  />
                  <text
                    x={Math.max(left + 40, Math.min(right - 40, boundary))}
                    y={18}
                    textAnchor="middle"
                  >
                    IS / OOS
                  </text>
                </g>
              )}
            {model.kind === "dataset" &&
              points.map((point, i) =>
                point.volume == null ? null : (
                  <rect
                    aria-hidden="true"
                    className="volume"
                    key={i}
                    x={x(point.time) - 1}
                    y={bottom + 34 - (point.volume / maxVolume) * 25}
                    width={2}
                    height={(point.volume / maxVolume) * 25}
                  />
                ),
              )}
            {model.series.map((series, index) => (
              <path
                key={series.label}
                className={series.className}
                aria-hidden="true"
                d={points
                  .map(
                    (p, i) =>
                      `${i ? "L" : "M"}${x(p.time).toFixed(2)},${y(p.values[index]).toFixed(2)}`,
                  )
                  .join(" ")}
              />
            ))}
            {points.length === 1 &&
              model.series.map((series, index) => (
                <circle
                  key={series.label}
                  className="chart-single-point"
                  cx={x(start)}
                  cy={y(points[0].values[index])}
                  r={4}
                />
              ))}
            <text x={left} y={size.height - 14}>
              {points[0].date}
            </text>
            {points.length > 1 && (
              <text x={right} y={size.height - 14} textAnchor="end">
                {points.at(-1)!.date}
              </text>
            )}
            {active && (
              <g aria-hidden="true" className="chart-selection">
                <line
                  className="chart-crosshair"
                  x1={cursorX}
                  x2={cursorX}
                  y1={top}
                  y2={bottom}
                />
                <line
                  className="chart-crosshair"
                  x1={left}
                  x2={right}
                  y1={cursorY}
                  y2={cursorY}
                />
                {active.values.map((value, index) => (
                  <circle
                    key={index}
                    className={`chart-point ${index === model.primary ? "primary-point" : "secondary-point"}`}
                    cx={cursorX}
                    cy={y(value)}
                    r={5}
                  />
                ))}
              </g>
            )}
          </svg>
        </div>
        {active && (
          <div
            className="chart-tooltip"
            role="status"
            aria-live="off"
            style={{ left: tooltipLeft, width: tooltipWidth }}
          >
            <strong>{active.label}</strong>
            <span className="caption">
              {Number.isFinite(boundaryTime)
                ? model.kind === "equity" &&
                  active.date === model.isEnd?.slice(0, 10)
                  ? "IS/OOS boundary day"
                  : active.time <= boundaryTime
                    ? "In-sample"
                    : "Out-of-sample"
                : "Recorded observation"}
            </span>
            <dl>
              {active.details.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
      <p id={helpId} className="caption chart-help">
        Hover or tap to inspect · ← → to move · Home / End
      </p>
    </>
  );
}

function Legend({ model }: { model: ChartModel }) {
  return (
    <div className="chart-legend">
      {model.series.map((series) => (
        <span
          key={series.label}
          className={series.className === "line-gross" ? "gross" : "net"}
        >
          {series.label}
        </span>
      ))}
    </div>
  );
}
function ExpandedChart({
  model,
  onClose,
  returnFocus,
}: {
  model: ChartModel;
  onClose: () => void;
  returnFocus: RefObject<HTMLButtonElement | null>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    const previous = returnFocus.current;
    const overflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [returnFocus]);
  return createPortal(
    <dialog
      className="chart-dialog"
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="row between chart-dialog-heading">
        <h2 id={titleId}>{model.title}</h2>
        <button onClick={onClose} autoFocus aria-label="Close expanded chart">
          Close ×
        </button>
      </div>
      <Legend model={model} />
      <div className="chart-frame">
        <Plot model={model} expanded />
      </div>
      <p className="caption">{model.caption}</p>
    </dialog>,
    document.body,
  );
}
export function InteractiveChart({ model }: { model: ChartModel }) {
  const [expanded, setExpanded] = useState(false);
  const expandButton = useRef<HTMLButtonElement>(null);
  return (
    <div className="interactive-chart-panel">
      <div className="chart-toolbar">
        <Legend model={model} />
        <button
          ref={expandButton}
          className="chart-expand"
          onClick={() => setExpanded(true)}
          aria-label={`Expand ${model.kind} chart`}
        >
          <span aria-hidden="true">⤢</span> Expand
        </button>
      </div>
      <div className="chart-frame">
        <Plot model={model} />
      </div>
      <p className="caption chart-caption">{model.caption}</p>
      {expanded && (
        <ExpandedChart
          model={model}
          onClose={() => setExpanded(false)}
          returnFocus={expandButton}
        />
      )}
    </div>
  );
}
