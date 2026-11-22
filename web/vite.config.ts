import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Chế độ mẫu đọc fixtures Accuracy ở tests/fixtures/accuracy/ (ngoài web/); đường dẫn tính từ root.
  server: { fs: { allow: [".", "../tests/fixtures/accuracy"] } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
