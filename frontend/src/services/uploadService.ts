import { apiClient } from "./client";
import { parseOrThrow } from "@/lib/validateResponse";
import {
  SampleListResponseSchema,
  UploadResponseSchema,
} from "@/types/api.schemas";
import type { SampleDataset, UploadResponse } from "@/types/api";

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

  async listSamples(): Promise<SampleDataset[]> {
    const { data } = await apiClient.get("/upload/samples");
    return parseOrThrow(
      SampleListResponseSchema,
      data,
      "uploadService.listSamples",
    ).samples;
  },

  // Returns the same UploadResponse a real file upload does — the caller
  // cannot tell the two apart, which is the point.
  async createFromSample(sampleId: string): Promise<UploadResponse> {
    const { data } = await apiClient.post<UploadResponse>(
      `/upload/sample/${encodeURIComponent(sampleId)}`,
    );
    return parseOrThrow(
      UploadResponseSchema,
      data,
      "uploadService.createFromSample",
    );
  },
};
