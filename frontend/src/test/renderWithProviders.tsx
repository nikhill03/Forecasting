import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

/**
 * Renders a component with the providers the app supplies in `main.tsx`.
 *
 * `App.tsx` does not include a QueryClientProvider — it lives only in
 * `main.tsx` — so any test that renders a component calling `useQuery` or
 * `useMutation` must bring its own. Retries are off: a failing request in a
 * test should surface immediately as an error state, not stall the test
 * while TanStack Query backs off and retries.
 *
 * A fresh QueryClient per call keeps the cache from leaking between tests.
 */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/" }: { route?: string } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
