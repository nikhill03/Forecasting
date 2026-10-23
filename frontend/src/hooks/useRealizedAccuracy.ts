import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { forecastService } from "@/services/forecastService";
import { ApiError } from "@/services/client";

export const realizedQueryKey = (jobId: string) => ["realized", jobId] as const;

/**
 * Realized accuracy for every metric of a finished job (F17). One request per
 * job — each metric card on the results page reads its own entry from it.
 */
export function useRealizedAccuracy(jobId: string) {
  return useQuery({
    queryKey: realizedQueryKey(jobId),
    queryFn: () => forecastService.getRealized(jobId),
    enabled: jobId !== "",
    staleTime: 30_000,
  });
}

/** Uploads that could supply actuals. Fetched only once the picker opens. */
export function useRealizedCandidates(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["realized-candidates", jobId],
    queryFn: () => forecastService.getRealizedCandidates(jobId),
    enabled: enabled && jobId !== "",
  });
}

/**
 * Check a job against one upload. The response is the full, current realized
 * state, so it is written straight into the cache instead of refetched; the
 * dashboard headline depends on it, so that summary is invalidated.
 */
export function useEvaluateRealized(jobId: string) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (uploadId: string) =>
      forecastService.evaluateRealized(jobId, uploadId),
    onSuccess: (data) => {
      queryClient.setQueryData(realizedQueryKey(jobId), data);
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
  });

  return {
    evaluate: mutation.mutate,
    isEvaluating: mutation.isPending,
    error:
      mutation.error instanceof ApiError
        ? mutation.error.message
        : mutation.error
          ? "Could not check this forecast. Try again."
          : null,
    reset: mutation.reset,
  };
}
