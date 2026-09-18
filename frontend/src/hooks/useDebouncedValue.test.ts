import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebouncedValue(60, 400));
    expect(result.current).toBe(60);
  });

  it("only settles on the last value once changes stop", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 400),
      { initialProps: { value: 60 } },
    );

    rerender({ value: 6 });
    act(() => vi.advanceTimersByTime(200));
    rerender({ value: 61 });
    act(() => vi.advanceTimersByTime(399));
    expect(result.current).toBe(60);

    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe(61);
  });
});
