import { MetricStat } from "@/components/ui/MetricStat";
import {
  formatFractionAsPercent,
  formatNumber,
  formatRelativeTime,
} from "@/lib/format";
import type { DashboardSummary } from "@/types/api";

interface StatStripProps {
  summary: DashboardSummary;
}

export function StatStrip({ summary }: StatStripProps) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:gap-6">
      <MetricStat
        label="Total runs"
        value={formatNumber(summary.total_runs, 0)}
      />
      <MetricStat
        label="Success rate"
        value={formatFractionAsPercent(summary.success_rate, 0)}
      />
      <MetricStat
        label="Median WMAPE"
        value={formatFractionAsPercent(summary.median_wmape, 1)}
      />
      <MetricStat
        label="Last run"
        value={formatRelativeTime(summary.last_run_at)}
      />
    </div>
  );
}
