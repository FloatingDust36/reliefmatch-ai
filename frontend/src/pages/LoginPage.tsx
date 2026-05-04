// frontend/src/pages/LoginPage.tsx

import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Step 1: get token
      const tokenRes = await api.post("/auth/login", { email, password });
      const { access_token } = tokenRes.data;

      // Step 2: get user profile using that token
      // We temporarily store it so the interceptor can attach it
      localStorage.setItem("access_token", access_token);
      const meRes = await api.get("/auth/me");

      // Step 3: commit to auth context (also writes to localStorage)
      login(access_token, meRes.data);

      // Step 4: role-based redirect
      const role = meRes.data.role;
      if (role === "lgu_coordinator" || role === "super_admin") {
        navigate("/coordinator");
      } else {
        navigate("/portal");
      }
    } catch (err: any) {
      // 401 = wrong credentials; other errors = server/network
      if (err.response?.status === 401) {
        setError("Invalid email or password.");
      } else {
        setError("Could not reach the server. Please try again.");
      }
      localStorage.removeItem("access_token");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-900 to-blue-700 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-8">
        {/* Header */}
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold text-gray-900">ReliefMatch AI</h1>
          <p className="text-sm text-gray-500 mt-1">
            AI-powered disaster relief allocation
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Email address
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="coordinator@cebucity.gov.ph"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Password
            </label>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200
                          rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50
                       text-white font-semibold rounded-lg py-2.5 text-sm
                       transition-colors duration-150"
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <p className="text-xs text-center text-gray-400 mt-6">
          Public transparency dashboard →{" "}
          <a href="/public" className="text-blue-500 hover:underline">
            View relief data
          </a>
        </p>
      </div>
    </div>
  );
}