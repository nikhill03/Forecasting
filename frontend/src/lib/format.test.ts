import { describe, it, expect } from "vitest";
import {
  formatNumber,
  formatPercent,
  formatFractionAsPercent,
  formatDuration,
  formatWmape,
  formatDate,
  formatFileSize,
} from "./format";

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [45, "45s"],
    [120, "2m"],
    [237, "3m 57s"],
    [236.94, "3m 57s"],
    [3600, "1h"],
    [3720, "1h 2m"],
    [3725, "1h 2m"],
  ])("formats %s seconds as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it.each([null, undefined, Number.NaN])("renders %s as a dash", (value) => {
    expect(formatDuration(value)).toBe("—");
  });

  it("never renders a negative duration", () => {
    expect(formatDuration(-5)).toBe("0s");
  });
});

describe("formatFractionAsPercent", () => {
  it("converts a fraction to a percentage", () => {
    expect(formatFractionAsPercent(0.0717)).toBe("7.2%");
  });

  it("respects the decimals argument", () => {
    expect(formatFractionAsPercent(0.9, 0)).toBe("90%");
  });

  it("renders a perfect score as 0%, not a dash", () => {
    expect(formatFractionAsPercent(0)).toBe("0.0%");
  });

  it.each([null, undefined])("renders %s as a dash, never 0%%", (value) => {
    expect(formatFractionAsPercent(value)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("formats a number with default 2 decimals", () => {
    expect(formatNumber(1234.5)).toBe("1,234.50");
  });

  it("returns em-dash for null", () => {
    expect(formatNumber(null)).toBe("—");
  });

  it("returns em-dash for undefined", () => {
    expect(formatNumber(undefined)).toBe("—");
  });

  it("returns em-dash for NaN", () => {
    expect(formatNumber(NaN)).toBe("—");
  });

  it("respects custom decimal places", () => {
    expect(formatNumber(1.23456, 4)).toBe("1.2346");
  });
});

describe("formatPercent", () => {
  it("formats with % suffix", () => {
    expect(formatPercent(85.456)).toBe("85.5%");
  });

  it("returns em-dash for null", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatWmape", () => {
  it("formats with 4 decimal places", () => {
    expect(formatWmape(0.123456)).toBe("0.1235");
  });

  it("returns em-dash for null", () => {
    expect(formatWmape(null)).toBe("—");
  });
});

describe("formatDate", () => {
  it("formats an ISO date string", () => {
    const result = formatDate("2024-03-15T00:00:00Z");
    expect(result).toMatch(/Mar/);
    expect(result).toMatch(/2024/);
  });

  it("returns em-dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("returns original string for invalid date", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("formatFileSize", () => {
  it("formats bytes under 1KB", () => {
    expect(formatFileSize(500)).toBe("500 B");
  });

  it("formats KB range", () => {
    expect(formatFileSize(2048)).toBe("2.0 KB");
  });

  it("formats MB range", () => {
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});