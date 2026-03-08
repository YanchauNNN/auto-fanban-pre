type ApiEnv = {
  DEV: boolean;
  VITE_API_BASE_URL?: string;
};

export function resolveApiBaseUrl(env: ApiEnv) {
  const configured = env.VITE_API_BASE_URL?.trim();
  if (configured) {
    return configured.replace(/\/+$/, "");
  }

  if (env.DEV) {
    return "http://127.0.0.1:8000";
  }

  return "";
}
