import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { WorkbenchProvider } from "./WorkbenchContext";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <WorkbenchProvider>
      <App />
    </WorkbenchProvider>
  </StrictMode>,
);
