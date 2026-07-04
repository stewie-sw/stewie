import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The cockpit is served by the FastAPI backend at /app (the vanilla cockpit stays at /). base=/app/ so the
// built asset URLs resolve there; outDir=dist is gitignored and built in CI + the Docker frontend image.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { port: 5173 },
});
