import { useEffect, useState } from "react";

/**
 * Returns `value` once it has stopped changing for `delayMs`. Used to keep
 * number inputs from firing a server request per keystroke.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
