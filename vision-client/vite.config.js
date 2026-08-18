import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 1428,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
});
