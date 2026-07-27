import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, MessageCircleQuestion, Send } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { forecastService } from "@/services/forecastService";
import { ApiError } from "@/services/client";
import { formatPercent, formatWmape } from "@/lib/format";
import type { MetricResult } from "@/types/api";

interface UnderstandabilitySectionProps {
  jobId: string;
  sheetName: string;
  metric: MetricResult;
}

interface QAPair {
  id: string;
  question: string;
  answer: string;
}

export function UnderstandabilitySection({
  jobId,
  sheetName,
  metric,
}: UnderstandabilitySectionProps) {
  const metricName = metric.metric_name ?? "";
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QAPair[]>([]);
  const [qaError, setQaError] = useState<string | null>(null);

  const {
    data: explanationData,
    isLoading: isExplanationLoading,
    isError: isExplanationError,
  } = useQuery({
    queryKey: ["forecast-explanation", jobId, sheetName, metricName],
    queryFn: () => forecastService.getExplanation(jobId, sheetName, metricName),
    staleTime: Infinity,
    enabled: !!metricName,
  });

  const qaMutation = useMutation({
    mutationFn: (q: string) =>
      forecastService.askQuestion(jobId, sheetName, metricName, q),
    onSuccess: (result, q) => {
      setHistory((prev) => [
        ...prev,
        { id: `${Date.now()}`, question: q, answer: result.answer },
      ]);
      setQuestion("");
      setQaError(null);
    },
    onError: (err) => {
      setQaError(
        err instanceof ApiError
          ? err.message
          : "Couldn't get an answer. Try again.",
      );
    },
  });

  return (
    <div className="mt-6 flex flex-col gap-4 border-t border-border pt-6">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-text">
          Understanding this forecast
        </h3>

        <div className="mb-4 grid grid-cols-2 gap-4 text-xs sm:grid-cols-4 lg:gap-6">
          <div>
            <span className="text-text-subtle">Model</span>
            <p className="text-text-muted">{metric.best_model ?? "—"}</p>
          </div>
          <div>
            <span className="text-text-subtle">Accuracy</span>
            <p className="text-text-muted">{formatPercent(metric.accuracy)}</p>
          </div>
          <div>
            <span className="text-text-subtle">WMAPE</span>
            <p className="text-text-muted">{formatWmape(metric.wmape)}</p>
          </div>
          <div>
            <span className="text-text-subtle">Demand type</span>
            <p className="text-text-muted">
              {metric.demand_profile?.demand_type ?? "—"}
            </p>
          </div>
        </div>

        {isExplanationLoading && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            Generating explanation…
          </div>
        )}
        {isExplanationError && (
          <p className="text-xs text-text-subtle">
            Explanation unavailable right now.
          </p>
        )}
        {explanationData && (
          <p className="text-sm leading-relaxed text-text-muted">
            {explanationData.explanation}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = question.trim();
            if (trimmed) qaMutation.mutate(trimmed);
          }}
          className="flex gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this forecast…"
            className="h-9 flex-1 rounded-md border border-border bg-bg-raised px-3 text-sm text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          <Button
            type="submit"
            size="sm"
            isLoading={qaMutation.isPending}
            disabled={!question.trim()}
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </form>

        {qaError && (
          <p role="alert" className="text-xs text-danger">
            {qaError}
          </p>
        )}

        {history.length > 0 && (
          <div className="flex flex-col gap-3">
            {history.map((pair) => (
              <div key={pair.id} className="flex flex-col gap-1">
                <p className="flex items-start gap-1.5 text-sm font-medium text-text">
                  <MessageCircleQuestion
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent"
                    aria-hidden="true"
                  />
                  {pair.question}
                </p>
                <p className="pl-5 text-sm text-text-muted">{pair.answer}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
