import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import dts from "vite-plugin-dts";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [
    react(),
    dts({
      include: ["src/viz-card"],
      rollupTypes: true,
      tsconfigPath: "./tsconfig.json",
    }),
  ],
  build: {
    lib: {
      entry: resolve(__dirname, "src/viz-card/index.ts"),
      name: "Data360McpUiVizCard",
      formats: ["es", "cjs"],
      fileName: (format) => `viz-card.${format === "es" ? "js" : "cjs"}`,
    },
    rollupOptions: {
      external: ["react", "react-dom", "vega", "vega-embed", "vega-lite"],
      output: {
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "vega-embed": "vegaEmbed",
        },
      },
    },
  },
});
