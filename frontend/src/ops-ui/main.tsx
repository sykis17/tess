import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { OpsAdminApp } from "./OpsAdminApp";
import "./ops-ui.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <OpsAdminApp />
  </StrictMode>,
);
