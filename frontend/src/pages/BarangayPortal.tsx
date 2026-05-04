import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";
export default function BarangayPortal() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  // TODO Week 4: fetch active events and list them here
  // Hard-coded event ID from seed data for now — replace with API call
  const SEEDED_EVENT_ID = "6809c261-d4d6-405f-b0c8-1387f4080ba1"; // paste your Typhoon Carina UUID from Neon here
  return (
    <div className="p-6 max-w-lg mx-auto">
      <h1 className="text-xl font-bold mb-1">Barangay Portal</h1>
      <p className="text-gray-500 text-sm mb-6">Welcome, {user?.full_name}</p>
      {SEEDED_EVENT_ID && (
        <button
          onClick={() => navigate(`/portal/report/${SEEDED_EVENT_ID}`)}
          className="w-full bg-blue-600 text-white rounded-xl py-4 font-bold"
        >
          File Damage Report — Typhoon Carina
        </button>
      )}
      <button onClick={logout} className="mt-4 text-sm text-red-500 hover:underline w-full text-left">
        Sign out
      </button>
    </div>
  );
}