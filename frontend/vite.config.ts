import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { apiProxyConfig } from "./src/tooling/viteProxy";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: apiProxyConfig,
  },
  preview: {
    proxy: apiProxyConfig,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
