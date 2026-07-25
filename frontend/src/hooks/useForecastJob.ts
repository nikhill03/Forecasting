import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { forecastService } from "@/services/forecastService";
import { useForecastStore } from "@/store/forecastStore";
import type { ForecastRequest } from "@/types/api";
import { ApiError } from "@/services/client";

const TERMINAL_STATES = new Set(["success", "failed", "stopped"]);

const FAST_INTERVAL_MS = 2000;
const SLOW_INTERVAL_MS = 5000;
const TIER_SWITCH_MS = 30000;

/**
 * Tiered polling: fast (2s) for the first 30s of a running job, then slow
 * (5s) — replaces the WebSocket progress channel cut from the original
 * Phase 2 roadmap. `startedAt` is null until the first successful fetch,
 * so a job that hasn't returned any data yet still polls at the fast tier.
 */
export function computeRefetchInterval(
  status: string | undefined,
  startedAt: number | null,
  now: number,
): number | false {
  if (status && TERMINAL_STATES.has(status)) return false;
  if (startedAt === null) return FAST_INTERVAL_MS;
  return now - startedAt < TIER_SWITCH_MS ? FAST_INTERVAL_MS : SLOW_INTERVAL_MS;
}

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
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    startedAtRef.current = null;
  }, [jobId]);

  return useQuery({
    queryKey: ["forecast-progress", jobId],
    queryFn: () => forecastService.getProgress(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (startedAtRef.current === null && query.state.data) {
        startedAtRef.current = Date.now();
      }
      return computeRefetchInterval(
        query.state.data?.status,
        startedAtRef.current,
        Date.now(),
      );
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