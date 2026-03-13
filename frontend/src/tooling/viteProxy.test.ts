// @vitest-environment node

import { describe, expect, it } from "vitest";

import { apiProxyConfig, apiProxyTarget } from "./viteProxy";

describe("vite proxy", () => {
  it("proxies /api requests to the local FastAPI service in dev and preview", () => {
    expect(apiProxyTarget).toBe("http://127.0.0.1:8000");
    expect(apiProxyConfig).toMatchObject({
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    });
  });
});
