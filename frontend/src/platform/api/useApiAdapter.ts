import { useMemo } from "react";

import { resolveApiBaseUrl } from "./apiBaseUrl";
import { HttpAdapter } from "./httpAdapter";

export function useApiAdapter() {
  const baseUrl = resolveApiBaseUrl(import.meta.env);

  return useMemo(
    () => new HttpAdapter(baseUrl),
    [baseUrl],
  );
}
