import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";
import { mockApi } from "./mock/plugin";

const strings = fileURLToPath(new URL("../strings", import.meta.url));

export default defineConfig({
  plugins: [preact(), mockApi()],
  resolve: {
    alias: { "@strings": strings },
  },
  server: {
    fs: { allow: [".", strings] },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "happy-dom",
    environmentOptions: { happyDOM: { url: "http://localhost:5173/" } },
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
