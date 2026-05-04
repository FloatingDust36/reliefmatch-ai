// frontend/src/context/AuthContext.tsx
//
// Global auth state — wraps the whole app so any component
// can read the current user and their role without prop drilling.
//
// Stored in localStorage so the user stays logged in on page refresh.
// The Axios interceptor in api.ts reads the token independently.

import { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface User {
  id: string;
  email: string;
  full_name: string;
  role: "super_admin" | "lgu_coordinator" | "barangay_official";
  lgu_id: string | null;
  barangay_id: string | null;
}

interface AuthContextType {
  user: User | null;
  login: (token: string, userData: User) => void;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true); // true until we check localStorage

  useEffect(() => {
    // On app load, restore user from localStorage if token exists.
    // This prevents the flash of the login screen on page refresh.
    const storedUser = localStorage.getItem("user");
    const token = localStorage.getItem("access_token");
    if (storedUser && token) {
      try {
        setUser(JSON.parse(storedUser));
      } catch {
        // Corrupt localStorage — clear it and force re-login
        localStorage.removeItem("user");
        localStorage.removeItem("access_token");
      }
    }
    setIsLoading(false);
  }, []);

  const login = (token: string, userData: User) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("user", JSON.stringify(userData));
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("user");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

// Custom hook — throw if used outside AuthProvider (catches setup mistakes early)
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}