import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { workerApi } from "./engine/client";
import { createAppStore } from "./store/store";

const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const store = createAppStore({ mode: "planning", utc: now, selectedSites: [] });
const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");
createRoot(root).render(
  <StrictMode>
    <App store={store} engineFor={typeof Worker === "undefined" ? undefined : workerApi} />
  </StrictMode>,
);
