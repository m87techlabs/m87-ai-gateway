import { useEffect, useMemo, useRef, useState } from "react";
import { compact, count, number } from "../format";
import type { Bucket } from "../types";
import { Empty } from "./ui";

type Field = "requests" | "total_tokens";

const niceMax = (value: number) => {
  if (value <= 4) return Math.max(2, Math.ceil(value / 2) * 2);
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 4, 6, 8, 10].find((item) => item * power >= value) ?? 10;
  return step * power;
};

/** Long windows read better as days than as hundreds of slivers. */
const bucketed = (series: Bucket[]) => {
  if (series.length <= 72) return { series, daily: false };
  const days = new Map<string, Bucket>();
  for (const item of series) {
    const day = item.bucket.slice(0, 10);
    const total = days.get(day) ?? { bucket: `${day}T00:00:00Z`, requests: 0, total_tokens: 0 };
    total.requests += item.requests;
    total.total_tokens += item.total_tokens;
    days.set(day, total);
  }
  return { series: [...days.values()], daily: true };
};

const when = (value: string, daily: boolean) =>
  new Date(value).toLocaleString(
    undefined,
    daily
      ? { month: "short", day: "numeric", timeZone: "UTC" }
      : { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
  );

/** One series over time: thin columns with a 4px data end, recessive axes and per-mark tooltips. */
export function ColumnChart({
  title,
  series,
  field,
  unit,
}: {
  title: string;
  series: Bucket[];
  field: Field;
  unit: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    const element = box.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const { series: points, daily } = useMemo(() => bucketed(series), [series]);
  const hasData = points.some((item) => item[field]);
  const height = 180;
  const left = 40;
  const bottom = 22;
  const top = 8;
  const plot = height - bottom - top;
  const maximum = niceMax(Math.max(1, ...points.map((item) => item[field])));
  const band = (width - left) / Math.max(1, points.length);
  const thickness = Math.max(1, Math.min(24, band - 2));
  const highlighted = active === null ? null : points[active];
  if (!hasData) {
    return (
      <figure className="chart">
        <figcaption>{title}</figcaption>
        <Empty title="No activity in this period" />
      </figure>
    );
  }
  return (
    <figure className="chart" ref={box}>
      <figcaption>{title}</figcaption>
      <div className="chart-plot" onPointerLeave={() => setActive(null)}>
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${title}, peak ${number(Math.max(...points.map((item) => item[field])))} ${unit}`}>
          {[0, 0.5, 1].map((fraction) => {
            const y = top + plot * (1 - fraction);
            return (
              <g key={fraction}>
                <line className="grid" x1={left} x2={width} y1={y} y2={y} />
                <text className="tick" x={left - 8} y={y + 4} textAnchor="end">
                  {compact(maximum * fraction)}
                </text>
              </g>
            );
          })}
          {points.map((item, index) => {
            const value = item[field];
            const barHeight = (value / maximum) * plot;
            const x = left + index * band + (band - thickness) / 2;
            const y = top + plot - barHeight;
            const radius = Math.min(4, thickness / 2, barHeight);
            return (
              <g key={item.bucket}>
                {value > 0 && (
                  <path
                    className={`bar${active === index ? " active" : ""}`}
                    d={`M${x},${y + barHeight}V${y + radius}Q${x},${y} ${x + radius},${y}H${x + thickness - radius}Q${x + thickness},${y} ${x + thickness},${y + radius}V${y + barHeight}Z`}
                  />
                )}
                <rect
                  className="hit"
                  data-testid="chart-hit"
                  x={left + index * band}
                  y={top}
                  width={band}
                  height={plot}
                  onPointerMove={() => setActive(index)}
                />
              </g>
            );
          })}
          <text className="tick" x={left} y={height - 6}>
            {when(points[0].bucket, daily)}
          </text>
          <text className="tick" x={width} y={height - 6} textAnchor="end">
            {when(points[points.length - 1].bucket, daily)}
          </text>
        </svg>
        {highlighted && active !== null && (
          <div
            className="chart-tip"
            style={{
              left: Math.min(width - 150, Math.max(left, left + active * band - 60)),
            }}
          >
            <strong>
              {number(highlighted[field])} {unit}
            </strong>
            <span className="muted">{when(highlighted.bucket, daily)}</span>
          </div>
        )}
      </div>
    </figure>
  );
}

export interface BarItem {
  key: string;
  label: string;
  value: number;
  detail?: string;
  href?: string;
}

/** A ranked comparison. Each bar carries its own label and value, so no legend is needed. */
export function BarList({ items, unit, empty }: { items: BarItem[]; unit: string; empty: string }) {
  if (!items.length) return <Empty title={empty} />;
  const singular = unit.replace(/s$/, "");
  const maximum = Math.max(1, ...items.map((item) => item.value));
  return (
    <ul className="bar-list">
      {items.map((item) => (
        <li key={item.key}>
          <div className="bar-list-head">
            {item.href ? <a href={item.href}>{item.label}</a> : <span>{item.label}</span>}
            <span className="muted" title={item.detail}>
              {count(item.value, singular)}
            </span>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${Math.max(1, (item.value / maximum) * 100)}%` }} />
          </div>
          {item.detail && <small className="muted">{item.detail}</small>}
        </li>
      ))}
    </ul>
  );
}
