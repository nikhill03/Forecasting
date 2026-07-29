import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { forecastService } from "./forecastService";
import { ApiError } from "./client";
import type { ForecastRequest } from "@/types/api";

const validForecastRequest: ForecastRequest = {
  upload_id: "upload-1",
  selected_sheets: ["Sheet1"],
  selected_metrics: ["Units"],
  forecast_horizon: 60,
  test_window: 30,
  selected_regions: ["US"],
  quantile_level: 0.75,
};

const validJob = {
  job_id: "job-1",
  status: "success" as const,
  name: "My forecast",
  progress: 100,
  message: "done",
  created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:01:00Z",
  completed_at: "2026-01-01T00:05:00Z",
  results: null,
  error: null,
};

describe("forecastService.getJob", () => {
  it("returns the parsed job for a well-formed response", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1", () => HttpResponse.json(validJob)),
    );

    const result = await forecastService.getJob("job-1");
    expect(result).toEqual(validJob);
  });

  it("rejects with ApiError when the response is missing a required field", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1", () => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { status, ...malformed } = validJob;
        return HttpResponse.json(malformed);
      }),
    );

    await expect(forecastService.getJob("job-1")).rejects.toThrow(ApiError);
  });

  it("parses successfully when a fully-populated job's nested metric_name and sheet_name are null", async () => {
    const jobWithNullNestedNames = {
      ...validJob,
      results: {
        Sheet1: {
          sheet_name: null,
          metrics: {
            wmape: {
              metric_name: null,
              best_model: "XGBoost",
              wmape: 12.34,
              mae: 5.6,
              mape: 8.9,
              rmse: 10.1,
              accuracy: 87.66,
              composite_score: 91.2,
              demand_profile: null,
              feature_importance: null,
              forecast_bias: 0.5,
              records: [],
            },
          },
        },
      },
    };

    server.use(
      http.get("*/api/v1/forecast/job-1", () =>
        HttpResponse.json(jobWithNullNestedNames),
      ),
    );

    const result = await forecastService.getJob("job-1");
    expect(result.results?.Sheet1?.sheet_name).toBeNull();
    expect(result.results?.Sheet1?.metrics.wmape?.metric_name).toBeNull();
  });
});

describe("forecastService.submitForecast", () => {
  it("returns the parsed job for a well-formed response", async () => {
    server.use(
      http.post("*/api/v1/forecast", () => HttpResponse.json(validJob)),
    );

    const result = await forecastService.submitForecast(validForecastRequest);
    expect(result).toEqual(validJob);
  });

  it("rejects an empty selected_sheets request payload before any network call is made", async () => {
    let submitCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast", () => {
        submitCallCount += 1;
        return HttpResponse.json(validJob);
      }),
    );

    await expect(
      forecastService.submitForecast({
        ...validForecastRequest,
        selected_sheets: [],
      }),
    ).rejects.toThrow(ApiError);
    expect(submitCallCount).toBe(0);
  });

  it("rejects a forecast_horizon above the allowed maximum before any network call is made", async () => {
    let submitCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast", () => {
        submitCallCount += 1;
        return HttpResponse.json(validJob);
      }),
    );

    await expect(
      forecastService.submitForecast({
        ...validForecastRequest,
        forecast_horizon: 9999,
      }),
    ).rejects.toThrow(ApiError);
    expect(submitCallCount).toBe(0);
  });
});

describe("forecastService.renameJob", () => {
  it("returns the parsed job for a well-formed response", async () => {
    server.use(
      http.patch("*/api/v1/forecast/job-1", () =>
        HttpResponse.json({ ...validJob, name: "Renamed" }),
      ),
    );

    const result = await forecastService.renameJob("job-1", "Renamed");
    expect(result).toEqual({ ...validJob, name: "Renamed" });
  });

  it("rejects a blank name request payload before any network call is made", async () => {
    let renameCallCount = 0;
    server.use(
      http.patch("*/api/v1/forecast/job-1", () => {
        renameCallCount += 1;
        return HttpResponse.json(validJob);
      }),
    );

    await expect(forecastService.renameJob("job-1", "")).rejects.toThrow(
      ApiError,
    );
    expect(renameCallCount).toBe(0);
  });
});

describe("forecastService.getProgress", () => {
  it("returns the parsed progress for a well-formed response", async () => {
    const validProgress = {
      job_id: "job-1",
      status: "running" as const,
      progress: 55,
      message: "training models",
    };
    server.use(
      http.get("*/api/v1/forecast/job-1/progress", () =>
        HttpResponse.json(validProgress),
      ),
    );

    const result = await forecastService.getProgress("job-1");
    expect(result).toEqual(validProgress);
  });

  it("rejects with ApiError when progress is a string instead of a number", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/progress", () =>
        HttpResponse.json({
          job_id: "job-1",
          status: "running",
          progress: "55%",
          message: "training models",
        }),
      ),
    );

    await expect(forecastService.getProgress("job-1")).rejects.toThrow(
      ApiError,
    );
  });
});

describe("forecastService.stopJob", () => {
  it("returns the parsed success response for a well-formed response", async () => {
    const validSuccess = { success: true as const, message: "Job stopped" };
    server.use(
      http.delete("*/api/v1/forecast/job-1", () =>
        HttpResponse.json(validSuccess),
      ),
    );

    const result = await forecastService.stopJob("job-1");
    expect(result).toEqual(validSuccess);
  });

  it("rejects with ApiError when success is false (the schema requires the literal true)", async () => {
    server.use(
      http.delete("*/api/v1/forecast/job-1", () =>
        HttpResponse.json({ success: false, message: "Job not found" }),
      ),
    );

    await expect(forecastService.stopJob("job-1")).rejects.toThrow(ApiError);
  });
});

describe("forecastService.getActionState / applyAction / revertAction", () => {
  it("getActionState returns the parsed action state for a well-formed response", async () => {
    const validState = { records: [], edits: [] };
    server.use(
      http.get("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json(validState),
      ),
    );

    const result = await forecastService.getActionState(
      "job-1",
      "Sheet1",
      "Units",
    );
    expect(result).toEqual(validState);
  });

  it("applyAction rejects a blank instruction_text request payload before any network call is made", async () => {
    let applyCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast/job-1/actions", () => {
        applyCallCount += 1;
        return HttpResponse.json({ records: [], edits: [] });
      }),
    );

    await expect(
      forecastService.applyAction("job-1", "Sheet1", "Units", ""),
    ).rejects.toThrow(ApiError);
    expect(applyCallCount).toBe(0);
  });

  it("applyAction rejects an instruction_text request payload over the 500-character maximum before any network call is made", async () => {
    let applyCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast/job-1/actions", () => {
        applyCallCount += 1;
        return HttpResponse.json({ records: [], edits: [] });
      }),
    );

    await expect(
      forecastService.applyAction("job-1", "Sheet1", "Units", "x".repeat(501)),
    ).rejects.toThrow(ApiError);
    expect(applyCallCount).toBe(0);
  });

  it("applyAction rejects with ApiError when the response's edits entries are missing sequence_no", async () => {
    server.use(
      http.post("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json({
          records: [],
          edits: [
            {
              id: "edit-1",
              instruction_text: "Smooth out the last 3 points",
              operation_type: "smooth",
              params: {},
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
        }),
      ),
    );

    await expect(
      forecastService.applyAction(
        "job-1",
        "Sheet1",
        "Units",
        "Smooth out the last 3 points",
      ),
    ).rejects.toThrow(ApiError);
  });

  it("revertAction rejects a request payload with a runtime-undefined sheet_name before any network call is made", async () => {
    // sheet_name has no length constraint on either the backend
    // (RevertActionRequest) or the frontend Zod schema beyond "required
    // string" — the only way to construct a payload that is TypeScript-valid
    // at the call site but fails the runtime Zod check is to simulate a
    // value reaching the function as something other than a string despite
    // the compile-time signature. `unknown` (never `any`) performs this cast.
    let revertCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast/job-1/actions/revert", () => {
        revertCallCount += 1;
        return HttpResponse.json({ records: [], edits: [] });
      }),
    );

    const runtimeUndefinedSheetName = undefined as unknown as string;

    await expect(
      forecastService.revertAction("job-1", runtimeUndefinedSheetName, "Units"),
    ).rejects.toThrow(ApiError);
    expect(revertCallCount).toBe(0);
  });
});

describe("forecastService.getExplanation / askQuestion", () => {
  it("getExplanation returns the parsed explanation for a well-formed response", async () => {
    const validExplanation = { explanation: "WMAPE improved after tuning." };
    server.use(
      http.get("*/api/v1/forecast/job-1/explanation", () =>
        HttpResponse.json(validExplanation),
      ),
    );

    const result = await forecastService.getExplanation(
      "job-1",
      "Sheet1",
      "Units",
    );
    expect(result).toEqual(validExplanation);
  });

  it("askQuestion rejects a blank question request payload before any network call is made", async () => {
    let qaCallCount = 0;
    server.use(
      http.post("*/api/v1/forecast/job-1/qa", () => {
        qaCallCount += 1;
        return HttpResponse.json({ answer: "unreachable" });
      }),
    );

    await expect(
      forecastService.askQuestion("job-1", "Sheet1", "Units", ""),
    ).rejects.toThrow(ApiError);
    expect(qaCallCount).toBe(0);
  });

  it("askQuestion rejects with ApiError when the response is missing answer", async () => {
    server.use(
      http.post("*/api/v1/forecast/job-1/qa", () => HttpResponse.json({})),
    );

    await expect(
      forecastService.askQuestion("job-1", "Sheet1", "Units", "Which model won?"),
    ).rejects.toThrow(ApiError);
  });
});

describe("forecastService.listJobs", () => {
  it("returns the parsed list for a well-formed response", async () => {
    server.use(
      http.get("*/api/v1/forecast", () =>
        HttpResponse.json({
          jobs: [
            {
              job_id: "job-1",
              status: "success",
              name: null,
              file_name: "data.csv",
              progress: 100,
              message: "done",
              created_at: "2026-01-01T00:00:00Z",
              started_at: null,
              completed_at: null,
              error: null,
              metrics: [],
            },
          ],
          total: 1,
        }),
      ),
    );

    const result = await forecastService.listJobs();
    expect(result.total).toBe(1);
    expect(result.jobs).toHaveLength(1);
  });

  it("rejects with ApiError when a job in the list is wrong-typed", async () => {
    server.use(
      http.get("*/api/v1/forecast", () =>
        HttpResponse.json({
          jobs: [{ job_id: "job-1", status: "success", progress: "not-a-number" }],
          total: 1,
        }),
      ),
    );

    await expect(forecastService.listJobs()).rejects.toThrow(ApiError);
  });

  it("rejects with ApiError when a job entry in the list is missing job_id", async () => {
    server.use(
      http.get("*/api/v1/forecast", () =>
        HttpResponse.json({
          jobs: [
            {
              status: "success",
              name: null,
              file_name: "data.csv",
              progress: 100,
              message: "done",
              created_at: "2026-01-01T00:00:00Z",
              started_at: null,
              completed_at: null,
              error: null,
              metrics: [],
            },
          ],
          total: 1,
        }),
      ),
    );

    await expect(forecastService.listJobs()).rejects.toThrow(ApiError);
  });
});
