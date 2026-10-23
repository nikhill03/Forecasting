import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  realizedQueryKey,
  useEvaluateRealized,
  useRealizedAccuracy,
  useRealizedCandidates,
} from "./useRealizedAccuracy";
import { server } from "@/test/server";
import { mockRealizedAwaiting, mockRealizedComplete } from "@/test/handlers";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper };
}

describe("useRealizedAccuracy", () => {
  it("loads the realized state for a job", async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useRealizedAccuracy("job-1"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(mockRealizedAwaiting));
  });
});

describe("useRealizedCandidates", () => {
  it("does not fetch until it is enabled", async () => {
    let requests = 0;
    server.use(
      http.get("*/api/v1/forecast/:jobId/realized/candidates", () => {
        requests += 1;
        return HttpResponse.json({ candidates: [] });
      }),
    );
    const { wrapper } = makeWrapper();
    const { result, rerender } = renderHook(
      ({ enabled }) => useRealizedCandidates("job-1", enabled),
      { wrapper, initialProps: { enabled: false } },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(requests).toBe(0);

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toEqual([]));
    expect(requests).toBe(1);
  });
});

describe("useEvaluateRealized", () => {
  it("writes the response into the cache and refreshes the dashboard summary", async () => {
    server.use(
      http.post("*/api/v1/forecast/job-1/realized", () =>
        HttpResponse.json(mockRealizedComplete),
      ),
    );
    const { client, wrapper } = makeWrapper();
    client.setQueryData(["dashboard-summary"], { stale: true });

    const { result } = renderHook(() => useEvaluateRealized("job-1"), { wrapper });
    act(() => result.current.evaluate("upload-actuals"));

    await waitFor(() =>
      expect(client.getQueryData(realizedQueryKey("job-1"))).toEqual(mockRealizedComplete),
    );
    expect(client.getQueryState(["dashboard-summary"])?.isInvalidated).toBe(true);
  });

  it("surfaces the server's reason when the file can't be used", async () => {
    server.use(
      http.post("*/api/v1/forecast/job-1/realized", () =>
        HttpResponse.json(
          { detail: "This file has none of the forecast's metric columns" },
          { status: 422 },
        ),
      ),
    );
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useEvaluateRealized("job-1"), { wrapper });
    act(() => result.current.evaluate("upload-x"));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toMatch(/none of the forecast's metric columns/);
  });
});
