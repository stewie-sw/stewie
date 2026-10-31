import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { fs: { allow: [".."] } }, // the contract schemas and fixtures live in ../crates/stewie-contracts
  test: { environment: "jsdom", globals: true },
});
