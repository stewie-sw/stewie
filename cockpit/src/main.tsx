import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@stewie/design-system/styles.css"; // tokens + fonts + component CSS (the design-system closure)
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
