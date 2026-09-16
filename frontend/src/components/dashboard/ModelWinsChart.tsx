import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { foldModelWins } from "@/lib/dashboard";
import type { ModelWin } from "@/types/api";
import { cn } from "@/lib/utils";

interface ModelWinsChartProps {
  // Most wins first, as the API sends them.
  wins: ModelWin[];
}

/**
 * Horizontal bars: how often each model was the champion.
 *
 * One measure across categories, so every bar is one hue — colour here says
 * "wins", not "which model"; the model name beside the bar carries identity.
 * "Other" recedes to a neutral. Bars are thin with a rounded data end and a
 * square baseline, the count sits at the bar's tip, and a hover tooltip adds
 * the share. Every value is also in a visually hidden table, so the tooltip
 * never gates a number.
 */
export function ModelWinsChart({ wins }: ModelWinsChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  const header = (
    <CardHeader>
      <div>
        <CardTitle>Which models win</CardTitle>
        <p className="mt-0.5 text-xs text-text-subtle">
          How often each model was the champion
        </p>
      </div>
    </CardHeader>
  );

  if (wins.length === 0) {
    return (
      <Card>
        {header}
        <CardContent>
          <p className="text-sm text-text-muted">No winning models recorded yet.</p>
        </CardContent>
      </Card>
    );
  }

  const total = wins.reduce((sum, w) => sum + w.wins, 0);
  const bars = foldModelWins(wins);
  const max = Math.max(...bars.map((b) => b.wins));

  const describe = (label: string, count: number) =>
    `${label} won ${count} of ${total} (${Math.round((count / total) * 100)}%)`;

  return (
    <Card>
      {header}
      <CardContent>
        <ul className="flex flex-col gap-2.5" aria-hidden="true">
          {bars.map((bar, i) => (
            <li
              key={bar.label}
              className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3"
            >
              <span className="truncate text-xs text-text-muted" title={bar.label}>
                {bar.label}
              </span>
              <div
                className="relative flex h-6 items-center gap-2"
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
              >
                <div
                  className={cn(
                    "h-3 rounded-r-[4px] transition-[filter]",
                    bar.isOther ? "bg-text-subtle" : "bg-accent",
                    hovered === i && "brightness-110",
                  )}
                  style={{
                    width: `max(4px, calc((100% - 2.5rem) * ${bar.wins / max}))`,
                  }}
                />
                <span className="font-mono text-xs tabular-nums text-text">
                  {bar.wins}
                </span>
                {hovered === i && (
                  <div className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 whitespace-nowrap rounded-md border border-border bg-bg-raised px-2 py-1 text-xs text-text shadow-elevated">
                    {describe(bar.label, bar.wins)}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>

        <table className="sr-only">
          <caption>Champion count per model, most wins first</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Wins</th>
              <th scope="col">Share</th>
            </tr>
          </thead>
          <tbody>
            {bars.map((bar) => (
              <tr key={bar.label}>
                <td>{bar.label}</td>
                <td>{bar.wins}</td>
                <td>{Math.round((bar.wins / total) * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
