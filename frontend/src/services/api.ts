// frontend/src/services/api.ts
//
// Central Axios instance for all ReliefMatch API calls.
// All components import from here — never call fetch() directly.
// This lets us:
//   1. Change the base URL in one place (env var)
//   2. Attach JWT to every request automatically
//   3. Handle 401 token expiry globally

import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL + "/api/v1",
  headers: { "Content-Type": "application/json" },
});

// Request interceptor — attach Bearer token if one exists in localStorage
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — if 401, token is expired or invalid.
// Clear storage and redirect to login so the user isn't stuck.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export default api;