/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/admin/",
  build: {
    outDir: "../src/m87_gateway/control/static",
    emptyOutDir: true,
    // The console's content security policy allows only scripts served from the gateway.
    modulePreload: { polyfill: false },
  },
  server: {
    proxy: {
      "/admin/api": "http://localhost:8087",
      "/v1": "http://localhost:8087",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: false,
  },
});
