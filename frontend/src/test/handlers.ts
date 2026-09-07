import { http, HttpResponse } from "msw";
import type {
  SampleDataset,
  TokenResponse,
  UploadResponse,
  UserResponse,
} from "@/types/api";

export const validTokenResponse: TokenResponse = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
};

export const mockUser: UserResponse = {
  id: "user-1",
  email: "test@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

// Mirrors backend SAMPLE_CATALOG closely enough to exercise the UI: three
// entries in three different demand quadrants.
export const mockSamples: SampleDataset[] = [
  {
    id: "retail-daily-smooth",
    title: "Retail store sales",
    description: "Two years of daily unit sales for a steady retail line.",
    demand_class: "Smooth",
    file_name: "retail-daily-smooth.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_sold", "marketing_spend", "avg_temp_c"],
  },
  {
    id: "spare-parts-intermittent",
    title: "Spare parts — intermittent",
    description: "Orders arrive on roughly one day in four.",
    demand_class: "Intermittent",
    file_name: "spare-parts-intermittent.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_shipped"],
  },
  {
    id: "spare-parts-lumpy",
    title: "Spare parts — lumpy",
    description: "Sporadic and erratic at once.",
    demand_class: "Lumpy",
    file_name: "spare-parts-lumpy.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_shipped"],
  },
];

export const mockSampleUpload: UploadResponse = {
  upload_id: "upload-from-sample-1",
  file_name: "retail-daily-smooth.csv",
  s3_key: "uploads/upload-from-sample-1/retail-daily-smooth.csv",
  sheets: ["Sheet1"],
  columns: { Sheet1: ["date", "units_sold", "marketing_spend", "avg_temp_c"] },
  row_counts: { Sheet1: 730 },
  uploaded_at: "2026-01-01T00:00:00Z",
};

export const handlers = [
  http.post("*/api/v1/auth/login", () => HttpResponse.json(validTokenResponse)),
  http.post("*/api/v1/auth/refresh", () => HttpResponse.json(validTokenResponse)),
  http.get("*/api/v1/auth/me", () => HttpResponse.json(mockUser)),
  http.get("*/api/v1/upload/samples", () =>
    HttpResponse.json({ samples: mockSamples }),
  ),
  http.post("*/api/v1/upload/sample/:sampleId", () =>
    HttpResponse.json(mockSampleUpload, { status: 201 }),
  ),
];
