import { useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { Loader2, Square } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Button } from "@/components/ui/Button";
import { useForecastStore } from "@/store/forecastStore";
import { useForecastWorkflow } from "@/hooks/useForecastJob";

export function RunningPage() {
  const navigate = useNavigate();
  const activeJobId = useForecastStore((s) => s.activeJobId);
  const { progress, isTerminal, stop, isStopping } = useForecastWorkflow();

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
          {!isTerminal && (
            <Loader2
              className="h-10 w-10 animate-spin text-accent"
              aria-hidden="true"
            />
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