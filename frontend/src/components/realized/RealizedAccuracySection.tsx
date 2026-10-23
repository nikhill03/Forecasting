import { useId, useState } from "react";
import { MetricStat } from "@/components/ui/MetricStat";
import { Button } from "@/components/ui/Button";
import { CheckActualsDialog } from "@/components/realized/CheckActualsDialog";
import { RealizedChart } from "@/components/realized/RealizedChart";
import { useRealizedAccuracy } from "@/hooks/useRealizedAccuracy";
import {
  formatDate,
  formatFractionAsPercent,
  formatNumber,
  formatRelativeTime,
} from "@/lib/format";
import type { RealizedMetric, RealizedScores } from "@/types/api";

interface RealizedAccuracySectionProps {
  jobId: string;
  sheetName: string;
  metricName: string;
}

// Under half a percent of net error reads as "no consistent bias" rather than
// a direction the data can't really support.
const BIAS_DEAD_ZONE = 0.005;

function describeBias(bias: number | null): string {
  if (bias === null) return "Bias is not available.";
  if (Math.abs(bias) < BIAS_DEAD_ZONE) return "No consistent over- or under-forecasting.";
  const size = formatFractionAsPercent(Math.abs(bias), 0);
  return bias > 0 ? `Over-forecast by ${size}.` : `Under-forecast by ${size}.`;
}

function ScoreBlock({ title, scores }: { title?: string; scores: RealizedScores }) {
  return (
    <div className="flex flex-col gap-2">
      {title && <h5 className="text-xs font-medium text-text-muted">{title}</h5>}
      <div className="grid grid-cols-2 gap-4">
        <MetricStat label="Realized WMAPE" value={formatFractionAsPercent(scores.wmape, 1)} />
        <MetricStat label="Realized MAE" value={formatNumber(scores.mae)} />
      </div>
      <p className="text-xs text-text-muted">
        {scores.wmape === null
          ? "Every actual was zero, so there is no percentage error to report."
          : describeBias(scores.bias)}
      </p>
    </div>
  );
}

function Measured({ metric }: { metric: RealizedMetric }) {
  if (!metric.model) return null;
  const adjusted = metric.adjusted;

  return (
    <div className="flex flex-col gap-4">
      <div className={adjusted ? "grid gap-6 sm:grid-cols-2" : undefined}>
        <ScoreBlock title={adjusted ? "Model forecast" : undefined} scores={metric.model} />
        {adjusted && <ScoreBlock title="Your adjusted forecast" scores={adjusted} />}
      </div>

      <p className="text-xs text-text-subtle">
        {metric.model.matched_points} of {metric.forecast_points} forecast dates measured
        {metric.upload_file_name && (
          <>
            , compared with {metric.upload_file_name}
            {metric.evaluated_at && <>, checked {formatRelativeTime(metric.evaluated_at)}</>}
          </>
        )}
        .
      </p>

      <RealizedChart points={metric.points} />
    </div>
  );
}

function noOverlapMessage(metric: RealizedMetric): string {
  const file = metric.upload_file_name ?? "That file";
  const last = metric.actuals_last_date;
  const start = metric.forecast_start;
  if (last && start && last < start) {
    return `${file} ends on ${formatDate(last)}, before this forecast starts on ${formatDate(start)}.`;
  }
  return `${file} has no values between ${formatDate(start)} and ${formatDate(metric.forecast_end)}.`;
}

// Realized accuracy is a different claim from the backtest stats above it:
// it compares the forecast with what actually happened later. It gets its own
// heading and numbers and is never folded into the backtest MetricStat row.
export function RealizedAccuracySection({
  jobId,
  sheetName,
  metricName,
}: RealizedAccuracySectionProps) {
  const { data, isError } = useRealizedAccuracy(jobId);
  const [isOpen, setIsOpen] = useState(false);
  const panelId = useId();

  const metric = data?.metrics.find(
    (m) => m.sheet_name === sheetName && m.metric_name === metricName,
  );

  if (isError) {
    return (
      <div className="mt-6 border-t border-border pt-6">
        <p className="text-xs text-text-subtle">
          Could not load how this forecast held up.
        </p>
      </div>
    );
  }
  if (!metric) return null;

  const hasScores = metric.status === "partial" || metric.status === "complete";

  return (
    <div className="mt-6 flex flex-col gap-4 border-t border-border pt-6">
      <h4 className="text-sm font-semibold text-text">How the forecast held up</h4>

      {metric.status === "awaiting_actuals" && (
        <p className="text-sm text-text-muted">
          This forecast covers {formatDate(metric.forecast_start)} to{" "}
          {formatDate(metric.forecast_end)}. Upload data that includes those
          dates to see how it held up.
        </p>
      )}
      {metric.status === "no_overlap" && (
        <p className="text-sm text-text-muted">{noOverlapMessage(metric)}</p>
      )}
      {hasScores && <Measured metric={metric} />}

      {isOpen ? (
        <CheckActualsDialog
          jobId={jobId}
          forecastStart={metric.forecast_start}
          forecastEnd={metric.forecast_end}
          panelId={panelId}
          onClose={() => setIsOpen(false)}
        />
      ) : (
        <div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsOpen(true)}
          >
            {metric.status === "awaiting_actuals"
              ? "Check against newer data"
              : "Check against another file"}
          </Button>
        </div>
      )}
    </div>
  );
}
