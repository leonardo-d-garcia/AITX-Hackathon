import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { Demo } from "@/demo/Demo";
import { WorkbenchProvider } from "./WorkbenchContext";
import "./styles.css";
import "@/demo/demo.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

// Two surfaces on one build: the workbench at /, the demo narrative at /demo. The demo renders
// the real supplied archive and shares the workbench palette and generated types.
const isDemo = window.location.pathname.startsWith("/demo");

createRoot(container).render(
  <StrictMode>
    {isDemo ? (
      <Demo />
    ) : (
      <WorkbenchProvider>
        <App />
      </WorkbenchProvider>
    )}
  </StrictMode>,
);
