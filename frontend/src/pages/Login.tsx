// frontend/src/pages/Login.tsx

import { useState } from "react";
import type { UserProfile } from "../App";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

interface LoginProps {
  onLoginSuccess: (user: UserProfile) => void;
}

export default function Login({ onLoginSuccess }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || "Login failed. Check your credentials.");
        return;
      }

      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);

      const meRes = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      const user: UserProfile = await meRes.json();

      if (!meRes.ok) {
        setError("Login succeeded but failed to load profile. Try again.");
        return;
      }

      onLoginSuccess(user);
    } catch {
      setError("Network error — is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div
        className="absolute inset-0 opacity-5"
        style={{
          backgroundImage:
            "linear-gradient(#3b82f6 1px, transparent 1px), linear-gradient(90deg, #3b82f6 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-5xl mb-4">🌀</div>
          <h1 className="text-3xl font-bold text-white tracking-tight">
            ReliefMatch <span className="text-blue-400">AI</span>
          </h1>
          <p className="text-gray-500 mt-2 text-sm">
            Disaster Relief Allocation · Philippine LGUs
          </p>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 shadow-2xl">
          <h2 className="text-lg font-semibold text-gray-100 mb-6">
            Sign in to your account
          </h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm text-gray-400 mb-1.5" htmlFor="email">
                Email address
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors placeholder-gray-600"
                placeholder="coordinator@cebu.gov.ph"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1.5" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors placeholder-gray-600"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="bg-red-900/30 border border-red-700 text-red-400 rounded-lg px-4 py-3 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg px-4 py-2.5 text-sm transition-colors"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>

          {/* Dev hint — remove before OJT demo */}
          <div className="mt-6 pt-5 border-t border-gray-800">
            <p className="text-xs text-gray-600 mb-2">Dev test credentials:</p>
            <div className="space-y-1">
              {(
                [
                  ["admin@reliefmatch.ph", "Admin@1234!", "super_admin"],
                  ["coordinator@cebu.gov.ph", "Coord@1234!", "lgu_coordinator"],
                  ["official@duljo.cebu.gov.ph", "Official@1234!", "barangay_official"],
                ] as const
              ).map(([e, p, role]) => (
                <button
                  key={e}
                  onClick={() => { setEmail(e); setPassword(p); setError(""); }}
                  className="w-full text-left px-3 py-1.5 rounded text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors font-mono"
                >
                  {role} → {e}
                </button>
              ))}
            </div>
          </div>
        </div>

        <p className="text-center text-gray-700 text-xs mt-6">
          ReliefMatch AI · OJT Portfolio · Computer Engineering
        </p>
      </div>
    </div>
  );
}