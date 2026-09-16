import { useId, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { formatDate, formatFractionAsPercent } from "@/lib/format";
import type { TrendPoint } from "@/types/api";

const WIDTH = 320;
const HEIGHT = 88;
const PAD_X = 14;
const PAD_Y = 14;

interface AccuracySparklineProps {
  // Oldest → newest, as the API returns them.
  points: TrendPoint[];
}

/**
 * Per-run WMAPE as a single-series line.
 *
 * Follows the stat-tile trend convention: the line is in a recessive tone and
 * only the latest point wears the accent. It plots the value directly — a
 * higher error sits higher — and says "lower is better", rather than inverting
 * the axis. Every value is also in a visually hidden table, so the hover
 * readout never gates a number.
 */
export function AccuracySparkline({ points }: AccuracySparklineProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const captionId = useId();

  const header = (
    <CardHeader>
      <div>
        <CardTitle>Accuracy over time</CardTitle>
        <p id={captionId} className="mt-0.5 text-xs text-text-subtle">
          Median WMAPE per run · lower is better
        </p>
      </div>
    </CardHeader>
  );

  if (points.length === 0) {
    return (
      <Card>
        {header}
        <CardContent>
          <p className="text-sm text-text-muted">
            No completed runs with a score yet.
          </p>
        </CardContent>
      </Card>
    );
  }

  const values = points.map((p) => p.wmape);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const lastIndex = points.length - 1;

  const x = (i: number) =>
    points.length === 1
      ? WIDTH / 2
      : PAD_X + (i * (WIDTH - 2 * PAD_X)) / lastIndex;
  const y = (v: number) =>
    span === 0 ? HEIGHT / 2 : PAD_Y + ((max - v) / span) * (HEIGHT - 2 * PAD_Y);

  const activeIndex = hovered ?? lastIndex;
  const active = points[activeIndex];
  const last = points[lastIndex];
  const first = points[0];

  if (!active || !last || !first) return null;

  const summary =
    points.length === 1
      ? `WMAPE ${formatFractionAsPercent(last.wmape)} for 1 run`
      : `WMAPE across the last ${points.length} runs, from ${formatFractionAsPercent(first.wmape)} to ${formatFractionAsPercent(last.wmape)}`;

  return (
    <Card>
      {header}
      <CardContent>
        <p
          data-testid="sparkline-readout"
          className="mb-2 flex items-baseline gap-2 text-xs"
          aria-live="polite"
        >
          <span className="text-base font-semibold text-text">
            {formatFractionAsPercent(active.wmape)}
          </span>
          <span className="text-text-muted">
            {formatDate(active.created_at)}
            {hovered === null && " · latest"}
          </span>
        </p>

        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full"
          role="group"
          aria-label={summary}
          aria-describedby={captionId}
        >
          {points.length > 1 && (
            <polyline
              points={points.map((p, i) => `${x(i)},${y(p.wmape)}`).join(" ")}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              className="stroke-text-subtle"
            />
          )}

          {hovered !== null && hovered !== lastIndex && (
            <circle
              cx={x(hovered)}
              cy={y(active.wmape)}
              r={4}
              strokeWidth={2}
              className="fill-text stroke-bg-surface"
            />
          )}

          <circle
            cx={x(lastIndex)}
            cy={y(last.wmape)}
            r={4}
            strokeWidth={2}
            className="fill-accent stroke-bg-surface"
          />

          {/* 24px hit targets — bigger than the 8px marks they sit on. */}
          {points.map((p, i) => (
            <circle
              key={p.job_id}
              cx={x(i)}
              cy={y(p.wmape)}
              r={12}
              fill="transparent"
              role="button"
              tabIndex={0}
              aria-label={`${formatDate(p.created_at)}: WMAPE ${formatFractionAsPercent(p.wmape)}`}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered(null)}
              className="cursor-default outline-none"
            />
          ))}
        </svg>

        {points.length === 1 && (
          <p className="mt-2 text-xs text-text-subtle">
            Run more forecasts to see a trend.
          </p>
        )}

        <table className="sr-only">
          <caption>WMAPE per run, oldest first</caption>
          <thead>
            <tr>
              <th scope="col">Run date</th>
              <th scope="col">WMAPE</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.job_id}>
                <td>{formatDate(p.created_at)}</td>
                <td>{formatFractionAsPercent(p.wmape)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
