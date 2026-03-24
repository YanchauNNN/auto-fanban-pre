import { defineConfig } from "vitest/config";
import legacy from "@vitejs/plugin-legacy";
import react from "@vitejs/plugin-react";
import { apiProxyConfig } from "./src/tooling/viteProxy";

export default defineConfig({
  plugins: [
    react(),
    legacy({
      targets: ["defaults", "not IE 11"],
    }),
  ],
  build: {
    cssTarget: "chrome61",
  },
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
