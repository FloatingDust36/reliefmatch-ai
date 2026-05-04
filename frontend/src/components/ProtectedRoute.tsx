// frontend/src/components/ProtectedRoute.tsx
//
// Guards any route that requires authentication.
// If no user is logged in → redirect to /login.
// If user doesn't have the required role → show 403 screen.
//
// Usage:
//   <ProtectedRoute allowedRoles={["lgu_coordinator"]}>
//     <CoordinatorDashboard />
//   </ProtectedRoute>

import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ReactNode } from "react";

interface Props {
  children: ReactNode;
  allowedRoles?: Array<"super_admin" | "lgu_coordinator" | "barangay_official">;
}

export default function ProtectedRoute({ children, allowedRoles }: Props) {
  const { user, isLoading } = useAuth();

  // While checking localStorage on app boot, show nothing (prevents login flash)
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500 text-sm">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="text-center">
          <p className="text-4xl font-bold text-red-500 mb-2">403</p>
          <p className="text-gray-700 font-medium">Access Denied</p>
          <p className="text-gray-500 text-sm mt-1">
            Your role ({user.role}) does not have permission to view this page.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}