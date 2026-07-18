import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { MetricStat } from "@/components/ui/MetricStat";
import { DemandBadge } from "@/components/ui/DemandBadge";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { formatWmape, formatPercent, formatNumber } from "@/lib/format";
import type { MetricResult } from "@/types/api";

interface MetricResultCardProps {
  metric: MetricResult;
}

export function MetricResultCard({ metric }: MetricResultCardProps) {
  return (
    <Card>
      <CardHeader className="flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <CardTitle>{metric.metric_name}</CardTitle>
          {metric.demand_profile && (
            <DemandBadge
              type={metric.demand_profile.demand_type}
              adi={metric.demand_profile.adi}
              cv2={metric.demand_profile.cv2}
              size="sm"
            />
          )}
        </div>
        {metric.best_model && (
          <span className="rounded-full bg-bg-raised px-2.5 py-1 text-2xs font-medium text-text-muted">
            {metric.best_model}
          </span>
        )}
      </CardHeader>

      <CardContent>
        <div className="mb-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetricStat label="WMAPE" value={formatWmape(metric.wmape)} />
          <MetricStat
            label="Accuracy"
            value={formatPercent(metric.accuracy)}
          />
          <MetricStat label="RMSE" value={formatNumber(metric.rmse)} />
          <MetricStat label="MAE" value={formatNumber(metric.mae)} />
        </div>

        <ForecastChart records={metric.records} />
      </CardContent>
    </Card>
  );
}