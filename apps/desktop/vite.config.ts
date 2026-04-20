import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@scene-pilot/shared": path.resolve(__dirname, "../../packages/shared/src/index.ts"),
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist-renderer",
  },
  server: {
    port: 5174,
    strictPort: true,
  },
});
