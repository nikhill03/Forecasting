import type { z } from "zod";
import { ApiError } from "@/services/client";

/**
 * Parses `data` against `schema`, returning the typed, stripped-of-unknown-
 * keys result. Throws the same `ApiError` the rest of the app already
 * catches (network failures, 4xx/5xx) so a contract violation is handled
 * identically to any other API failure, with no new error type for callers
 * to learn.
 */
export function parseOrThrow<T>(
  schema: z.ZodType<T>,
  data: unknown,
  context: string,
): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    console.error(`[validateResponse] ${context}`, result.error.issues);
    throw new ApiError(
      "Invalid response shape from server",
      0,
      result.error.issues,
    );
  }
  return result.data;
}
