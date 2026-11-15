import { resolve } from "node:path";

export default {
  base: "./",
  build: {
    emptyOutDir: false,
    outDir: resolve(import.meta.dirname, "web/chess-replay/assets"),
    rollupOptions: {
      input: resolve(import.meta.dirname, "web/chess-replay/src/main.jsx"),
      output: {
        entryFileNames: "chess-review.js",
        chunkFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
};
