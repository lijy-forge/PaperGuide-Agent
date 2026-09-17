import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    pool: "forks",
    poolOptions: { forks: { singleFork: true } },
    // Routes are React.lazy chunks. A browser fetches them over HTTP, but here
    // Vite compiles each page and its antd/pdfjs dependency graph on first
    // navigation, which measured ~4.2s. The defaults (5s per test, 1s per
    // findBy) sit right on that edge, so navigation tests failed sporadically.
    testTimeout: 20000,
    hookTimeout: 20000
  }
});
