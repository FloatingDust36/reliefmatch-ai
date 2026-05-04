import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";
import api from "../services/api";

interface DisasterEvent {
  id: string;
  name: string;
  disaster_type: string;
}

export default function BarangayPortal() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [activeEvent, setActiveEvent] = useState<DisasterEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function fetchActiveEvent() {
      try {
        const res = await api.get("/events/", { params: { status: "active" } });
        if (res.data.length > 0) {
          setActiveEvent(res.data[0]);
        }
      } catch (err) {
        setError("Could not load events. Check your connection.");
      } finally {
        setLoading(false);
      }
    }
    fetchActiveEvent();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-400 text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-lg mx-auto">
      <h1 className="text-xl font-bold mb-1">Barangay Portal</h1>
      <p className="text-gray-500 text-sm mb-6">Welcome, {user?.full_name}</p>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200
                      rounded-lg px-3 py-2 mb-4">
          {error}
        </p>
      )}

      {!activeEvent && !error && (
        <p className="text-sm text-gray-400">
          No active disaster events right now.
        </p>
      )}

      {activeEvent && (
        <button
          onClick={() => navigate(`/portal/report/${activeEvent.id}`)}
          className="w-full bg-blue-600 text-white rounded-xl py-4 font-bold"
        >
          File Damage Report — {activeEvent.name}
        </button>
      )}

      <button
        onClick={logout}
        className="mt-4 text-sm text-red-500 hover:underline w-full text-left"
      >
        Sign out
      </button>
    </div>
  );
}