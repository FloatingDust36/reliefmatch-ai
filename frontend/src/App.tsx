// frontend/src/App.tsx

import { useState, useEffect } from "react";
import Login from "./pages/Login";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

// ── Shared type — also imported by Login.tsx ──────────────────────────────────
// Mirrors UserMeResponse from backend/app/schemas/auth.py.
// If you add a field there, add it here too.
export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: "super_admin" | "lgu_coordinator" | "barangay_official";
  lgu_id: string | null;
  barangay_id: string | null;
  is_active: boolean;
}

// Role → dashboard label — TypeScript now knows exactly which keys are valid
const ROLE_LABELS: Record<UserProfile["role"], string> = {
  super_admin: "System Administrator Dashboard",
  lgu_coordinator: "LGU Coordinator Dashboard",
  barangay_official: "Barangay Official Portal",
};

export default function App() {
  // Typed as UserProfile | null — fixes every "Property does not exist on type 'never'" error
  const [user, setUser] = useState<UserProfile | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      setBootstrapping(false);
      return;
    }

    fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Token invalid");
        return res.json();
      })
      .then((userData: UserProfile) => {
        setUser(userData);
      })
      .catch(() => {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
      })
      .finally(() => {
        setBootstrapping(false);
      });
  }, []);

  // Typed parameter — fixes "Parameter 'userData' implicitly has an 'any' type"
  function handleLoginSuccess(userData: UserProfile) {
    setUser(userData);
  }

  function handleLogout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  }

  if (bootstrapping) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-gray-600 text-sm animate-pulse">Loading…</div>
      </div>
    );
  }

  if (!user) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl">🌀</span>
          <span className="font-bold text-blue-400">ReliefMatch AI</span>
          <span className="text-gray-600 text-sm">·</span>
          <span className="text-gray-400 text-sm">{ROLE_LABELS[user.role]}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-gray-400 text-sm">{user.full_name}</span>
          <button
            onClick={handleLogout}
            className="text-sm text-gray-500 hover:text-red-400 transition-colors"
          >
            Sign out
          </button>
        </div>
      </nav>

      <div className="flex items-center justify-center mt-24">
        <div className="text-center space-y-4">
          <div className="inline-block bg-green-500/20 border border-green-500 text-green-400 px-4 py-2 rounded-full text-sm">
            ✅ Auth working — JWT verified
          </div>
          <div className="text-gray-400 space-y-1 text-sm">
            <p><span className="text-gray-600">User:</span> {user.email}</p>
            <p><span className="text-gray-600">Role:</span> <span className="text-blue-400">{user.role}</span></p>
            {user.lgu_id && <p><span className="text-gray-600">LGU ID:</span> {user.lgu_id}</p>}
          </div>
          <p className="text-gray-700 text-xs mt-8">Week 4: React Router + real dashboards</p>
        </div>
      </div>
    </div>
  );
}