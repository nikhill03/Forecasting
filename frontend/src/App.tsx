import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { DashboardPage } from "@/pages/DashboardPage";
import { UploadPage } from "@/pages/UploadPage";
import { ConfigurePage } from "@/pages/ConfigurePage";
import { RunningPage } from "@/pages/RunningPage";
import { ResultsPage } from "@/pages/ResultsPage";
import { LoginPage } from "@/pages/LoginPage";
import { useAuthStore } from "@/store/authStore";
import { authService } from "@/services/authService";

export function App() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  useEffect(() => {
    if (!accessToken || user) {
      return;
    }

    let cancelled = false;
    authService
      .getMe()
      .then((profile) => {
        if (!cancelled) {
          setUser(profile);
        }
      })
      .catch(() => {
        // apiClient's response interceptor already attempts a refresh and
        // calls logout() on failure — nothing extra to do here.
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, user, setUser]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/configure" element={<ConfigurePage />} />
            <Route path="/running" element={<RunningPage />} />
            <Route path="/results" element={<ResultsPage />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
