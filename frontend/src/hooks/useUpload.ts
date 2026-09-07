import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { uploadService } from "@/services/uploadService";
import { useForecastStore } from "@/store/forecastStore";
import { ApiError } from "@/services/client";

export function useUpload() {
  const [progress, setProgress] = useState(0);
  const setUpload = useForecastStore((s) => s.setUpload);

  const mutation = useMutation({
    mutationFn: (file: File) =>
      uploadService.uploadFile(file, (pct) => setProgress(pct)),
    onSuccess: (data) => {
      setUpload(data);
      setProgress(0);
    },
    onError: () => {
      setProgress(0);
    },
  });

  return {
    upload: mutation.mutate,
    isUploading: mutation.isPending,
    progress,
    error:
      mutation.error instanceof ApiError ? mutation.error.message : null,
    reset: mutation.reset,
  };
}

// The sample catalog is fixed for the lifetime of a deployment, so there is
// nothing to revalidate against.
export function useSamples() {
  return useQuery({
    queryKey: ["samples"],
    queryFn: () => uploadService.listSamples(),
    staleTime: Infinity,
  });
}

// Deliberately mirrors useUpload's onSuccess: both flows land on the same
// setUpload transition, so /configure cannot tell a sample from a real file.
export function useSampleUpload() {
  const setUpload = useForecastStore((s) => s.setUpload);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (sampleId: string) => {
      setPendingId(sampleId);
      return uploadService.createFromSample(sampleId);
    },
    onSuccess: (data) => {
      setUpload(data);
      setPendingId(null);
    },
    onError: () => {
      setPendingId(null);
    },
  });

  return {
    createFromSample: mutation.mutate,
    isCreating: mutation.isPending,
    pendingId,
    error:
      mutation.error instanceof ApiError ? mutation.error.message : null,
  };
}