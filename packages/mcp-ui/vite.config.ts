import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import dts from "vite-plugin-dts";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [
    react(),
    dts({
      include: ["src/viz-card", "src/search-card"],
      rollupTypes: true,
      tsconfigPath: "./tsconfig.json",
    }),
  ],
  build: {
    lib: {
      // Multi-entry: each surface builds to its own output file
      entry: {
        "viz-card": resolve(__dirname, "src/viz-card/index.ts"),
        "search-card": resolve(__dirname, "src/search-card/index.ts"),
      },
      formats: ["es", "cjs"],
      fileName: (format, entryName) =>
        `${entryName}.${format === "es" ? "js" : "cjs"}`,
    },
    rollupOptions: {
      external: [
        "@data360/chart-payload-normalize",
        "@data360/mcp-viz-core",
        "@data360/tool-types",
        "react",
        "react-dom",
        "vega",
        "vega-embed",
        "vega-lite",
      ],
      output: {
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "vega-embed": "vegaEmbed",
          "@data360/mcp-viz-core": "Data360McpVizCore",
          "@data360/tool-types": "Data360ToolTypes",
        },
      },
    },
  },
});
