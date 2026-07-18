import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { forecastService } from "@/services/forecastService";
import { useForecastStore } from "@/store/forecastStore";
import type { ForecastRequest } from "@/types/api";
import { ApiError } from "@/services/client";

const TERMINAL_STATES = new Set(["success", "failed", "stopped"]);

export function useSubmitForecast() {
  const setActiveJobId = useForecastStore((s) => s.setActiveJobId);

  const mutation = useMutation({
    mutationFn: (request: ForecastRequest) =>
      forecastService.submitForecast(request),
    onSuccess: (data) => {
      setActiveJobId(data.job_id);
    },
  });

  return {
    submit: mutation.mutate,
    isSubmitting: mutation.isPending,
    error:
      mutation.error instanceof ApiError ? mutation.error.message : null,
  };
}

export function useForecastProgress(jobId: string | null) {
  return useQuery({
    queryKey: ["forecast-progress", jobId],
    queryFn: () => forecastService.getProgress(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL_STATES.has(status)) return false;
      return 2000;
    },
  });
}

export function useForecastResult(jobId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["forecast-result", jobId],
    queryFn: () => forecastService.getJob(jobId!),
    enabled: !!jobId && enabled,
  });
}

export function useForecastWorkflow() {
  const activeJobId = useForecastStore((s) => s.activeJobId);
  const setStep = useForecastStore((s) => s.setStep);
  const queryClient = useQueryClient();

  const progressQuery = useForecastProgress(activeJobId);
  const isTerminal =
    !!progressQuery.data && TERMINAL_STATES.has(progressQuery.data.status);

  const resultQuery = useForecastResult(activeJobId, isTerminal);

  useEffect(() => {
    if (isTerminal && progressQuery.data?.status === "success") {
      setStep("results");
    }
  }, [isTerminal, progressQuery.data?.status, setStep]);

  const stopMutation = useMutation({
    mutationFn: () => forecastService.stopJob(activeJobId!),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["forecast-progress", activeJobId],
      });
    },
  });

  return {
    progress: progressQuery.data,
    result: resultQuery.data,
    isLoadingResult: resultQuery.isLoading,
    isTerminal,
    stop: stopMutation.mutate,
    isStopping: stopMutation.isPending,
  };
}