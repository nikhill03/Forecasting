import { CircleCheck, OctagonX, TriangleAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataQualityReport, SeriesQuality } from "@/types/api";
import { groupIssues } from "@/lib/qualityIssues";
import { QualityIssueList } from "./QualityIssueList";

const FREQUENCY_LABELS: Record<string, string> = {
  D: "Daily",
  B: "Business days",
  h: "Hourly",
  H: "Hourly",
  MS: "Monthly",
  ME: "Monthly",
  M: "Monthly",
  QS: "Quarterly",
};

function frequencyLabel(freq: string | null): string {
  if (!freq) return "Irregular";
  if (freq.startsWith("W")) return "Weekly";
  return FREQUENCY_LABELS[freq] ?? freq;
}

/** What the pipeline will actually train on, for one series. */
function SeriesFacts({ series }: { series: SeriesQuality }) {
  const facts: [string, string][] = [
    ["Usable points", formatNumber(series.usable_points, 0)],
    [
      "Dates",
      series.start && series.end
        ? `${formatDate(series.start)} to ${formatDate(series.end)}`
        : "None found",
    ],
  ];
  // A blocked series never reaches the split or horizon cap, so the
  // profiler leaves those unset (0) — don't present them as real numbers.
  if (series.test_split_size > 0) {
    facts.push(
      ["Spacing", frequencyLabel(series.inferred_frequency)],
      ["Held out for testing", `${series.test_split_size} points`],
      ["Forecast length", `${series.effective_horizon} days`],
    );
  }

  return (
    <div>
      <p className="mb-1.5 font-mono text-xs text-text-muted">
        {series.sheet} / {series.metric}
      </p>
      <dl className="flex flex-wrap gap-x-8 gap-y-2">
        {facts.map(([term, value]) => (
          <div key={term} className="min-w-[7rem]">
            <dt className="text-xs text-text-subtle">{term}</dt>
            <dd className="text-sm text-text">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface DataQualityPanelProps {
  report: DataQualityReport | undefined;
  isLoading?: boolean;
  isFetching?: boolean;
  isError?: boolean;
  /** Why no check is running, when none is. */
  idleReason?: "no-selection" | "invalid-settings" | null;
  className?: string;
}

export function DataQualityPanel({
  report,
  isLoading = false,
  isFetching = false,
  isError = false,
  idleReason = null,
  className,
}: DataQualityPanelProps) {
  const blocking = report ? groupIssues(report, "blocking") : [];
  const warnings = report ? groupIssues(report, "warning") : [];

  let body;
  if (report) {
    body = (
      <div className="flex flex-col gap-5">
        {blocking.length > 0 && (
          <section
            aria-labelledby="quality-blocking"
            className="rounded-md border border-danger/40 bg-danger/5 p-4"
          >
            <h4
              id="quality-blocking"
              className="mb-3 flex items-center gap-2 text-sm font-semibold text-danger"
            >
              <OctagonX className="h-4 w-4" aria-hidden="true" />
              Must fix before running
            </h4>
            <QualityIssueList groups={blocking} severity="blocking" />
          </section>
        )}

        {warnings.length > 0 && (
          <section aria-labelledby="quality-warnings">
            <h4
              id="quality-warnings"
              className="mb-3 flex items-center gap-2 text-sm font-semibold text-text"
            >
              <TriangleAlert className="h-4 w-4 text-warning" aria-hidden="true" />
              Worth knowing
            </h4>
            <QualityIssueList groups={warnings} severity="warning" />
          </section>
        )}

        {blocking.length === 0 && warnings.length === 0 && (
          <p className="flex items-center gap-2 text-sm text-text">
            <CircleCheck className="h-4 w-4 text-success" aria-hidden="true" />
            No issues found in {report.series.length} series.
          </p>
        )}

        {report.series.length > 0 && (
          <div className="flex flex-col gap-4 border-t border-border pt-4">
            {report.series.map((series) => (
              <SeriesFacts
                key={`${series.sheet}/${series.metric}`}
                series={series}
              />
            ))}
          </div>
        )}
      </div>
    );
  } else if (isError) {
    body = (
      <p className="text-sm text-text-muted">
        Couldn't check this data. You can still run the forecast — the check
        runs again when you do.
      </p>
    );
  } else if (isLoading) {
    body = <p className="text-sm text-text-muted">Checking your data…</p>;
  } else {
    body = (
      <p className="text-sm text-text-subtle">
        {idleReason === "invalid-settings"
          ? "Enter a forecast horizon of 1–365 days and a test window of 7–180 days to check the data."
          : "Pick a sheet and a metric to check the data before running."}
      </p>
    );
  }

  return (
    <Card className={className} aria-busy={isFetching}>
      <CardHeader>
        <CardTitle>Data check</CardTitle>
        {report && isFetching && (
          <span className="text-xs text-text-subtle" role="status">
            Updating…
          </span>
        )}
      </CardHeader>
      <CardContent className={cn(report && isFetching && "opacity-70")}>
        {body}
      </CardContent>
    </Card>
  );
}
