import { existsSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import legacy from "@vitejs/plugin-legacy";
import react from "@vitejs/plugin-react";
import { apiProxyConfig } from "./src/tooling/viteProxy";

const configDir = fileURLToPath(new URL(".", import.meta.url));
const nodeModulesDir = fileURLToPath(new URL("./node_modules", import.meta.url));
const devServerFsAllow = [configDir];

if (existsSync(nodeModulesDir)) {
  devServerFsAllow.push(realpathSync(nodeModulesDir));
}

export default defineConfig({
  plugins: [
    react(),
    legacy({
      targets: ["defaults", "not IE 11"],
    }),
  ],
  resolve: {
    alias: [
      {
        find: /^pdfjs-dist$/,
        replacement: "pdfjs-dist/legacy/build/pdf.mjs",
      },
    ],
  },
  build: {
    cssTarget: "chrome61",
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.split("\\").join("/");
          if (!normalizedId.includes("/node_modules/")) {
            return undefined;
          }

          if (
            normalizedId.includes("/react-pdf/") ||
            normalizedId.includes("/pdfjs-dist/")
          ) {
            return "pdf-preview-vendor";
          }

          if (
            normalizedId.includes("/react/") ||
            normalizedId.includes("/react-dom/") ||
            normalizedId.includes("/scheduler/")
          ) {
            return "react-vendor";
          }

          if (normalizedId.includes("/@tanstack/react-query/")) {
            return "query-vendor";
          }

          if (
            normalizedId.includes("/react-router") ||
            normalizedId.includes("/@remix-run/")
          ) {
            return "router-vendor";
          }

          return undefined;
        },
      },
    },
  },
  server: {
    fs: {
      allow: devServerFsAllow,
    },
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
