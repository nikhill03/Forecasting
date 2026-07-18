import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { UploadPage } from "@/pages/UploadPage";
import { ConfigurePage } from "@/pages/ConfigurePage";
import { RunningPage } from "@/pages/RunningPage";
import { ResultsPage } from "@/pages/ResultsPage";
import { LoginPage } from "@/pages/LoginPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/configure" element={<ConfigurePage />} />
          <Route path="/running" element={<RunningPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}