import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
import tsconfigPaths from "vite-tsconfig-paths";
import fs from "node:fs";
import path from "node:path";

const versionFile = path.resolve(__dirname, "../../version.json");
const releaseMeta = fs.existsSync(versionFile)
  ? JSON.parse(fs.readFileSync(versionFile, "utf8"))
  : { version: "", build: "" };

export default defineConfig({
  plugins: [
    TanStackRouterVite({
      routesDirectory: "./src/routes",
      generatedRouteTree: "./src/routeTree.gen.ts",
      routeFileIgnorePattern: "(sitemap|README)",
    }),
    react(),
    tailwindcss(),
    tsconfigPaths(),
  ],
  define: {
    __MBT_DASHBOARD_VERSION__: JSON.stringify(String(releaseMeta.version || "")),
    __MBT_DASHBOARD_BUILD__: JSON.stringify(String(releaseMeta.build || "")),
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          tanstack: [
            "@tanstack/react-router",
            "@tanstack/react-query",
            "@tanstack/router-core",
          ],
          icons: ["lucide-react"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:5050", changeOrigin: true },
    },
  },
});
