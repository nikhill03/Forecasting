import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { AlertTriangle, Square, XCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Button } from "@/components/ui/Button";
import { PipelineStepper } from "@/components/forecast/PipelineStepper";
import { useForecastStore } from "@/store/forecastStore";
import { useForecastWorkflow } from "@/hooks/useForecastJob";

export function RunningPage() {
  const navigate = useNavigate();
  const activeJobId = useForecastStore((s) => s.activeJobId);
  const { progress, result, isTerminal, stop, isStopping } = useForecastWorkflow();

  useEffect(() => {
    if (!activeJobId) navigate("/upload");
  }, [activeJobId, navigate]);

  useEffect(() => {
    if (progress?.status === "success") navigate("/results");
    if (progress?.status === "failed" || progress?.status === "stopped") {
      // stay on page, show terminal state with retry option
    }
  }, [progress?.status, navigate]);

  if (!activeJobId) return null;

  const isFailed = progress?.status === "failed";
  const isStopped = progress?.status === "stopped";

  return (
    <div className="mx-auto max-w-xl">
      <Card>
        <CardContent className="flex flex-col items-center gap-6 py-12 text-center">
          {isFailed && (
            <XCircle className="h-10 w-10 text-danger" aria-hidden="true" />
          )}
          {isStopped && (
            <Square className="h-10 w-10 text-text-muted" aria-hidden="true" />
          )}

          <div>
            <h2 className="text-lg font-semibold text-text">
              {isFailed
                ? "Forecast failed"
                : isStopped
                  ? "Forecast stopped"
                  : "Running forecast"}
            </h2>
            <p
              className="mt-1 text-sm text-text-muted"
              role="status"
              aria-live="polite"
            >
              {progress?.message ?? "Initializing…"}
            </p>
          </div>

          {!isStopped && (
            <PipelineStepper message={progress?.message} isFailed={isFailed} />
          )}

          {isFailed && result?.error && (
            <div
              role="alert"
              className="flex w-full items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2.5 text-left text-sm text-danger"
            >
              <AlertTriangle
                className="mt-0.5 h-4 w-4 shrink-0"
                aria-hidden="true"
              />
              <span>{result.error}</span>
            </div>
          )}

          {!isTerminal && (
            <ProgressBar
              value={progress?.progress ?? 0}
              className="w-full max-w-sm"
            />
          )}

          {!isTerminal && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => stop()}
              isLoading={isStopping}
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              Stop forecast
            </Button>
          )}

          {(isFailed || isStopped) && (
            <Button onClick={() => navigate("/upload")} variant="secondary">
              Start a new forecast
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}