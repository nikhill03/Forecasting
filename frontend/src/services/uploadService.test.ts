import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { uploadService } from "./uploadService";
import { ApiError } from "./client";

const validUpload = {
  upload_id: "upload-1",
  file_name: "data.csv",
  s3_key: "uploads/upload-1/data.csv",
  sheets: ["Sheet1"],
  columns: { Sheet1: ["Date", "Value"] },
  row_counts: { Sheet1: 100 },
  uploaded_at: "2026-01-01T00:00:00Z",
};

describe("uploadService.getUpload", () => {
  it("returns the parsed upload for a well-formed response", async () => {
    server.use(
      http.get("*/api/v1/upload/upload-1", () =>
        HttpResponse.json(validUpload),
      ),
    );

    const result = await uploadService.getUpload("upload-1");
    expect(result).toEqual(validUpload);
  });

  it("rejects with ApiError when the response is missing a required field", async () => {
    server.use(
      http.get("*/api/v1/upload/upload-1", () => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { sheets, ...malformed } = validUpload;
        return HttpResponse.json(malformed);
      }),
    );

    await expect(uploadService.getUpload("upload-1")).rejects.toThrow(
      ApiError,
    );
  });

  it("rejects with ApiError when row_counts values are wrong-typed (strings instead of numbers)", async () => {
    server.use(
      http.get("*/api/v1/upload/upload-1", () =>
        HttpResponse.json({
          ...validUpload,
          row_counts: { Sheet1: "100" },
        }),
      ),
    );

    await expect(uploadService.getUpload("upload-1")).rejects.toThrow(
      ApiError,
    );
  });

  it("resolves successfully and strips an unrelated extra field instead of throwing", async () => {
    server.use(
      http.get("*/api/v1/upload/upload-1", () =>
        HttpResponse.json({ ...validUpload, checksum: "sha256:deadbeef" }),
      ),
    );

    const result = await uploadService.getUpload("upload-1");
    expect(result).toEqual(validUpload);
    expect(result).not.toHaveProperty("checksum");
  });
});

// uploadFile's request body is FormData (multipart), which hangs under this
// project's MSW + jsdom + axios XHR-adapter combination regardless of the
// request handler used — reproduced with a bare `apiClient.post(url, formData)`
// call with zero uploadService code involved, so it's an environment
// limitation, not something parseOrThrow introduces. uploadFile shares the
// exact same UploadResponseSchema/parseOrThrow return path as getUpload
// above, which is covered over a real MSW round trip.
