import { describe, it, expect } from "vitest";
import { z } from "zod";
import { parseOrThrow } from "./validateResponse";
import { ApiError } from "@/services/client";

const PersonSchema = z.object({
  name: z.string(),
  age: z.number(),
});

describe("parseOrThrow", () => {
  it("returns the parsed data unchanged for a valid payload", () => {
    const data = { name: "Ada", age: 30 };
    expect(parseOrThrow(PersonSchema, data, "test")).toEqual(data);
  });

  it("throws an ApiError with status 0 when a required field is missing", () => {
    const data = { name: "Ada" };
    expect(() => parseOrThrow(PersonSchema, data, "test")).toThrow(ApiError);
    try {
      parseOrThrow(PersonSchema, data, "test");
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(0);
      expect((err as ApiError).message).toBe(
        "Invalid response shape from server",
      );
    }
  });

  it("strips unknown extra keys instead of throwing", () => {
    const data = { name: "Ada", age: 30, unexpected: "field" };
    const result = parseOrThrow(PersonSchema, data, "test");
    expect(result).toEqual({ name: "Ada", age: 30 });
    expect(result).not.toHaveProperty("unexpected");
  });
});

const WidgetSchema = z.object({
  id: z.string(),
  tags: z.array(z.string()),
  meta: z.object({ count: z.number() }).nullable(),
});

describe("parseOrThrow — nested and nullable fields", () => {
  it("passes a valid payload with a nullable field explicitly set to null", () => {
    const data = { id: "widget-1", tags: [], meta: null };
    expect(parseOrThrow(WidgetSchema, data, "test")).toEqual(data);
  });

  it("throws when a nested field has the wrong runtime type", () => {
    const data = { id: "widget-2", tags: ["a"], meta: { count: "three" } };
    expect(() => parseOrThrow(WidgetSchema, data, "test")).toThrow(ApiError);
  });

  it("strips an unknown field nested inside an object property instead of throwing", () => {
    const data = {
      id: "widget-3",
      tags: [],
      meta: { count: 5, extra: "should be dropped" },
    };
    const result = parseOrThrow(WidgetSchema, data, "test");
    expect(result.meta).toEqual({ count: 5 });
  });

  it("attaches the Zod issues array as `detail` on the thrown ApiError", () => {
    const data = { id: "widget-4", tags: ["x"] }; // missing `meta`
    try {
      parseOrThrow(WidgetSchema, data, "test");
      expect.unreachable("parseOrThrow should have thrown");
    } catch (err) {
      const apiErr = err as ApiError;
      expect(Array.isArray(apiErr.detail)).toBe(true);
      expect((apiErr.detail as unknown[]).length).toBeGreaterThan(0);
    }
  });
});
