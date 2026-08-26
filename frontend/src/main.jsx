import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import DashboardPage from "./pages/DashboardPage";
import ProjectPage from "./pages/ProjectPage";
import ProjectSettingsPage from "./pages/ProjectSettingsPage";
import ProjectBrandPage from "./pages/project/brand";
import PageBuilderPage from "./pages/PageBuilderPage";
import AgentsPage from "./pages/AgentsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import LibraryPage from "./pages/LibraryPage";
import ProjectSeoPage from "./pages/project/seo";
import ProjectDeploymentsPage from "./pages/project/deployments";
import ProjectNavigationPage from "./pages/ProjectNavigationPage";
import ApiKeysPage from "./pages/ApiKeysPage";
import ModelsPage from "./pages/ModelsPage";
import SettingsPage from "./pages/SettingsPage";
import { AppProvider } from "./context/AppContext";
import { ThemeProvider } from "./context/ThemeContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <AppProvider>
        <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<DashboardPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="settings/api-keys" element={<ApiKeysPage />} />
            <Route path="settings/models" element={<ModelsPage />} />
            <Route path="project/:projectId" element={<ProjectPage />} />
            <Route path="project/:projectId/settings" element={<ProjectSettingsPage />} />
            <Route path="project/:projectId/brand" element={<ProjectBrandPage />} />
            <Route path="project/:projectId/navigation" element={<ProjectNavigationPage />} />
            <Route path="project/:projectId/library" element={<LibraryPage />} />
            <Route path="project/:projectId/seo" element={<ProjectSeoPage />} />
            <Route path="project/:projectId/deployments" element={<ProjectDeploymentsPage />} />
          </Route>
          <Route
            path="project/:projectId/page/:slug"
            element={<PageBuilderPage />}
          />
          </Routes>
        </BrowserRouter>
      </AppProvider>
    </ThemeProvider>
  </React.StrictMode>
);
