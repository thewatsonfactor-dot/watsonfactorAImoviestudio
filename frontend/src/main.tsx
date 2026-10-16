import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { Shell, Toasts } from "./components/Shell";
import { StudioProvider, useStudio } from "./lib/store";
import Create from "./pages/Create";
import Library from "./pages/Library";
import Models from "./pages/Models";
import Renders from "./pages/Renders";
import Settings from "./pages/Settings";

function Router() {
  const { route } = useStudio();
  return (
    <Shell>
      {route === "create" && <Create />}
      {route === "renders" && <Renders />}
      {route === "library" && <Library />}
      {route === "models" && <Models />}
      {route === "settings" && <Settings />}
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StudioProvider>
      <Router />
      <Toasts />
    </StudioProvider>
  </StrictMode>,
);
