import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MetricResultCard } from "@/components/forecast/MetricResultCard";
import { useForecastStore } from "@/store/forecastStore";
import { useForecastResult } from "@/hooks/useForecastJob";

export function ResultsPage() {
  const navigate = useNavigate();
  const activeJobId = useForecastStore((s) => s.activeJobId);
  const reset = useForecastStore((s) => s.reset);
  const { data: result, isLoading } = useForecastResult(activeJobId, true);

  useEffect(() => {
    if (!activeJobId) navigate("/upload");
  }, [activeJobId, navigate]);

  const handleNewForecast = () => {
    reset();
    navigate("/upload");
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-text-muted">
        Loading results…
      </div>
    );
  }

  if (!activeJobId || !result?.results) {
    return (
      <div className="flex h-64 items-center justify-center text-text-muted">
        No results available.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text">
            Forecast results
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            {Object.keys(result.results).length} sheet
            {Object.keys(result.results).length !== 1 ? "s" : ""} processed
          </p>
        </div>
        <Button variant="secondary" onClick={handleNewForecast}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          New forecast
        </Button>
      </div>

      <div className="space-y-8">
        {Object.entries(result.results).map(([sheetName, sheetResult]) => (
          <section key={sheetName} aria-labelledby={`sheet-${sheetName}`}>
            <h2
              id={`sheet-${sheetName}`}
              className="mb-3 text-sm font-semibold uppercase tracking-wide text-text-subtle"
            >
              {sheetName}
            </h2>
            <div className="space-y-4">
              {Object.values(sheetResult.metrics).map((metric) => (
                <MetricResultCard
                  key={metric.metric_name}
                  metric={metric}
                  jobId={activeJobId}
                  sheetName={sheetName}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}