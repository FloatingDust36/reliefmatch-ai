// frontend/src/App.tsx

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";

// Pages — we'll create these below
import LoginPage from "./pages/LoginPage";
import CoordinatorDashboard from "./pages/CoordinatorDashboard";
import BarangayPortal from "./pages/BarangayPortal";
import DamageReportForm from "./pages/DamageReportForm";
import PublicDashboard from "./pages/PublicDashboard";

// Root redirect — sends logged-in users to the right dashboard
function RootRedirect() {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "lgu_coordinator" || user.role === "super_admin") {
    return <Navigate to="/coordinator" replace />;
  }
  return <Navigate to="/portal" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/public" element={<PublicDashboard />} />

          {/* LGU Coordinator */}
          <Route
            path="/coordinator/*"
            element={
              <ProtectedRoute allowedRoles={["lgu_coordinator", "super_admin"]}>
                <CoordinatorDashboard />
              </ProtectedRoute>
            }
          />

          {/* Barangay Official */}
          <Route
            path="/portal"
            element={
              <ProtectedRoute allowedRoles={["barangay_official"]}>
                <BarangayPortal />
              </ProtectedRoute>
            }
          />
          <Route
            path="/portal/report/:eventId"
            element={
              <ProtectedRoute allowedRoles={["barangay_official"]}>
                <DamageReportForm />
              </ProtectedRoute>
            }
          />

          {/* Default */}
          <Route path="/" element={<RootRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}