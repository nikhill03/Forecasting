import { useMutation } from "@tanstack/react-query";
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