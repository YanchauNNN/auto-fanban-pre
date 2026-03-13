export const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export const apiProxyConfig = {
  "/api": {
    target: apiProxyTarget,
    changeOrigin: true,
  },
};
