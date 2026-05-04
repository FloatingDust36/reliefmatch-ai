// frontend/src/pages/CoordinatorDashboard.tsx
//
// LGU Coordinator's main workspace.
// Layout: sidebar (event info + supply management) + map panel.
//
// Data flow:
//   1. On mount → GET /events/?status=active → grab first active event
//   2. On event load → GET /events/{id}/supplies → populate supply table
//   3. Log Goods form → POST /events/{id}/supplies → refresh supply list
//   4. Map receives barangay data derived from damage reports (Week 6 adds scores)

import { useState, useEffect, FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";
import BarangayMap from "../components/BarangayMap";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DisasterEvent {
  id: string;
  name: string;
  disaster_type: string;
  status: string;
  declared_at: string;
}

interface Supply {
  id: string;
  goods_type: string;
  quantity: number;
  unit: string;
  source_name: string;
  received_at: string;
}

// Goods type → display label + color
const GOODS_META: Record<string, { label: string; color: string }> = {
  food_pack:  { label: "Food Pack",   color: "bg-orange-100 text-orange-800" },
  water:      { label: "Water",       color: "bg-blue-100 text-blue-800" },
  medicine:   { label: "Medicine",    color: "bg-red-100 text-red-800" },
  clothing:   { label: "Clothing",    color: "bg-purple-100 text-purple-800" },
  hygiene_kit:{ label: "Hygiene Kit", color: "bg-green-100 text-green-800" },
  other:      { label: "Other",       color: "bg-gray-100 text-gray-700" },
};

const DISASTER_ICONS: Record<string, string> = {
  typhoon: "🌀", earthquake: "🌍", flood: "🌊",
  landslide: "⛰️", fire: "🔥",
};

// ── Log Goods Form State ──────────────────────────────────────────────────────

const EMPTY_FORM = {
  goods_type: "food_pack",
  quantity: "",
  unit: "packs",
  source_name: "",
  warehouse_latitude: "10.3157",   // Default: Cebu City Hall coords
  warehouse_longitude: "123.8854",
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function CoordinatorDashboard() {
  const { user, logout } = useAuth();

  const [event, setEvent] = useState<DisasterEvent | null>(null);
  const [supplies, setSupplies] = useState<Supply[]>([]);
  const [loadingEvent, setLoadingEvent] = useState(true);
  const [loadingSupplies, setLoadingSupplies] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  // ── Fetch active event on mount ──────────────────────────────────────────

  useEffect(() => {
    async function fetchEvent() {
      try {
        const res = await api.get("/events/", { params: { status: "active" } });
        // Take the first active event for this coordinator's LGU
        if (res.data.length > 0) {
          setEvent(res.data[0]);
        }
      } catch (err) {
        console.error("Failed to fetch events", err);
      } finally {
        setLoadingEvent(false);
      }
    }
    fetchEvent();
  }, []);

  // ── Fetch supplies when event is known ───────────────────────────────────

  useEffect(() => {
    if (!event) return;
    fetchSupplies();
  }, [event]);

  async function fetchSupplies() {
    if (!event) return;
    setLoadingSupplies(true);
    try {
      const res = await api.get(`/events/${event.id}/supplies`);
      setSupplies(res.data);
    } catch (err) {
      console.error("Failed to fetch supplies", err);
    } finally {
      setLoadingSupplies(false);
    }
  }

  // ── Log Goods submit ─────────────────────────────────────────────────────

  async function handleLogGoods(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setFormSuccess("");

    if (!form.source_name.trim()) {
      setFormError("Source name is required.");
      return;
    }
    if (!form.quantity || Number(form.quantity) <= 0) {
      setFormError("Quantity must be greater than 0.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post(`/events/${event!.id}/supplies`, {
        goods_type: form.goods_type,
        quantity: Number(form.quantity),
        unit: form.unit,
        source_name: form.source_name.trim(),
        warehouse_latitude: Number(form.warehouse_latitude),
        warehouse_longitude: Number(form.warehouse_longitude),
      });
      setFormSuccess("Supply logged successfully.");
      setForm(EMPTY_FORM);
      setShowForm(false);
      fetchSupplies(); // Refresh the table
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setFormError(typeof detail === "string" ? detail : "Failed to log supply.");
    } finally {
      setSubmitting(false);
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-PH", {
      month: "short", day: "numeric", year: "numeric",
    });
  }

  // Group supplies by type for the summary row
  const supplyTotals = supplies.reduce<Record<string, number>>((acc, s) => {
    acc[s.goods_type] = (acc[s.goods_type] || 0) + s.quantity;
    return acc;
  }, {});

  // ── Render ────────────────────────────────────────────────────────────────

  if (loadingEvent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-400 text-sm">Loading event data…</p>
      </div>
    );
  }

  if (!event) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="text-center">
          <p className="text-2xl mb-2">🌤️</p>
          <p className="font-semibold text-gray-700">No active disaster events</p>
          <p className="text-sm text-gray-400 mt-1">
            When an event is declared, it will appear here.
          </p>
          <button
            onClick={logout}
            className="mt-6 text-sm text-red-500 hover:underline"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-100 flex flex-col overflow-hidden">

      {/* ── Top nav ── */}
      <header className="bg-blue-800 text-white px-6 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold tracking-tight">ReliefMatch AI</span>
          <span className="text-blue-300 text-sm hidden sm:block">
            LGU Coordinator Dashboard
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-blue-200 hidden sm:block">
            {user?.full_name}
          </span>
          <button
            onClick={logout}
            className="text-sm bg-blue-700 hover:bg-blue-600 px-3 py-1.5
                       rounded-lg transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ── Main layout: sidebar + map ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── LEFT SIDEBAR ── */}
        <aside className="w-full max-w-sm bg-white border-r border-gray-200
                          flex flex-col overflow-y-auto">

          {/* Event header */}
          <div className="p-4 border-b border-gray-100 bg-red-50">
            <div className="flex items-start gap-3">
              <span className="text-3xl">
                {DISASTER_ICONS[event.disaster_type] ?? "⚠️"}
              </span>
              <div>
                <p className="font-bold text-gray-900 text-sm leading-tight">
                  {event.name}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Declared {formatDate(event.declared_at)}
                </p>
                <span className="inline-block mt-1.5 text-xs font-semibold
                                 bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                  ● ACTIVE
                </span>
              </div>
            </div>
          </div>

          {/* Supply summary badges */}
          <div className="p-4 border-b border-gray-100">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Available Supplies
            </p>
            {Object.keys(supplyTotals).length === 0 && !loadingSupplies ? (
              <p className="text-xs text-gray-400">No supplies logged yet.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {Object.entries(supplyTotals).map(([type, total]) => {
                  const meta = GOODS_META[type] ?? GOODS_META.other;
                  return (
                    <span
                      key={type}
                      className={`text-xs font-medium px-2.5 py-1 rounded-full ${meta.color}`}
                    >
                      {meta.label}: {total.toLocaleString()}
                    </span>
                  );
                })}
              </div>
            )}
          </div>

          {/* Log Goods button + success message */}
          <div className="p-4 border-b border-gray-100">
            {formSuccess && (
              <p className="text-xs text-green-700 bg-green-50 border border-green-200
                            rounded-lg px-3 py-2 mb-3">
                ✓ {formSuccess}
              </p>
            )}
            <button
              onClick={() => { setShowForm(!showForm); setFormError(""); setFormSuccess(""); }}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm
                         font-semibold rounded-xl py-2.5 transition-colors"
            >
              {showForm ? "✕ Cancel" : "+ Log Incoming Goods"}
            </button>
          </div>

          {/* Log Goods form — collapsible */}
          {showForm && (
            <form onSubmit={handleLogGoods} className="p-4 border-b border-gray-100 space-y-3">

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Goods Type
                </label>
                <select
                  value={form.goods_type}
                  onChange={e => setForm(f => ({ ...f, goods_type: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2
                             text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {Object.entries(GOODS_META).map(([val, { label }]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Quantity
                  </label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={form.quantity}
                    onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))}
                    placeholder="e.g. 500"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2
                               text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Unit
                  </label>
                  <select
                    value={form.unit}
                    onChange={e => setForm(f => ({ ...f, unit: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2
                               text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="packs">packs</option>
                    <option value="kg">kg</option>
                    <option value="liters">liters</option>
                    <option value="boxes">boxes</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Source / Donor
                </label>
                <input
                  type="text"
                  required
                  value={form.source_name}
                  onChange={e => setForm(f => ({ ...f, source_name: e.target.value }))}
                  placeholder="e.g. DSWD Region VII"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2
                             text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Warehouse coords — pre-filled to Cebu City Hall, editable */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Warehouse Lat
                  </label>
                  <input
                    type="number"
                    step="0.0000001"
                    value={form.warehouse_latitude}
                    onChange={e => setForm(f => ({ ...f, warehouse_latitude: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2
                               text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Warehouse Lng
                  </label>
                  <input
                    type="number"
                    step="0.0000001"
                    value={form.warehouse_longitude}
                    onChange={e => setForm(f => ({ ...f, warehouse_longitude: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2
                               text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              {formError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-200
                              rounded-lg px-3 py-2">
                  {formError}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-50
                           text-white text-sm font-semibold rounded-xl py-2.5
                           transition-colors"
              >
                {submitting ? "Saving…" : "Save Supply Record"}
              </button>
            </form>
          )}

          {/* Supply inventory table */}
          <div className="p-4 flex-1">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
              Inventory Log
            </p>
            {loadingSupplies ? (
              <p className="text-xs text-gray-400">Loading…</p>
            ) : supplies.length === 0 ? (
              <p className="text-xs text-gray-400">No records yet.</p>
            ) : (
              <div className="space-y-2">
                {supplies.map(s => {
                  const meta = GOODS_META[s.goods_type] ?? GOODS_META.other;
                  return (
                    <div
                      key={s.id}
                      className="flex items-start justify-between bg-gray-50
                                 rounded-xl px-3 py-2.5 text-xs"
                    >
                      <div>
                        <span className={`font-semibold px-1.5 py-0.5 rounded
                                         ${meta.color}`}>
                          {meta.label}
                        </span>
                        <p className="text-gray-500 mt-1 leading-tight">
                          {s.source_name}
                        </p>
                        <p className="text-gray-400">
                          {formatDate(s.received_at)}
                        </p>
                      </div>
                      <div className="text-right font-bold text-gray-800 whitespace-nowrap ml-2">
                        {s.quantity.toLocaleString()}
                        <span className="font-normal text-gray-400 ml-1">{s.unit}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </aside>

        {/* ── RIGHT PANEL: Map ── */}
        <main className="flex-1 relative min-h-0">
          {event && <BarangayMap eventId={event.id} />}
        </main>

      </div>
    </div>
  );
}