import { useMemo } from "react";

import { HttpAdapter } from "./httpAdapter";

export function useApiAdapter() {
  return useMemo(
    () => new HttpAdapter(import.meta.env.VITE_API_BASE_URL ?? ""),
    [],
  );
}
