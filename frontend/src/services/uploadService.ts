import { apiClient } from "./client";
import { parseOrThrow } from "@/lib/validateResponse";
import { UploadResponseSchema } from "@/types/api.schemas";
import type { UploadResponse } from "@/types/api";

export const uploadService = {
  async uploadFile(
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append("file", file);

    const { data } = await apiClient.post<UploadResponse>(
      "/upload",
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (event) => {
          if (onProgress && event.total) {
            onProgress(Math.round((event.loaded / event.total) * 100));
          }
        },
      },
    );
    return parseOrThrow(
      UploadResponseSchema,
      data,
      "uploadService.uploadFile",
    );
  },

  async getUpload(uploadId: string): Promise<UploadResponse> {
    const { data } = await apiClient.get<UploadResponse>(
      `/upload/${uploadId}`,
    );
    return parseOrThrow(UploadResponseSchema, data, "uploadService.getUpload");
  },
};
