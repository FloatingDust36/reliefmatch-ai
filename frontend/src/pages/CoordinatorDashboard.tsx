// frontend/src/pages/CoordinatorDashboard.tsx
//
// LGU Coordinator's main workspace.
// Layout: sidebar (event info + supply management) + tabbed main panel.
//
// Tab 1 — Map: Leaflet map with color-coded barangay urgency markers.
//          Marker colors come from real priority_score once allocation
//          has been run; falls back to client-side heuristic before that.
//
// Tab 2 — Allocations: AI-generated ranked dispatch plan.
//          Shows XGBoost score, SHAP explanation, truck/stop routing,
//          goods quantities, and approve/dispatch action buttons.
//
// Data flow:
//   1. On mount → GET /events/?status=active → grab first active event
//   2. On event load → GET /events/{id}/supplies → populate supply table
//   3. On event load → GET /events/{id}/allocations → populate allocation table
//   4. "Run AI Allocation" → POST /events/{id}/allocate → refresh allocations
//   5. "Approve" button → PATCH /allocations/{id}/approve → update row status

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

interface Allocation {
  id: string;
  barangay_name: string;
  goods_type: string;
  quantity_allocated: number;
  priority_score: number;
  priority_rank: number;
  shap_explanation: string;
  status: string;
  approved_at: string | null;
  dispatched_at: string | null;
  delivered_at: string | null;
}

// ── Display helpers ───────────────────────────────────────────────────────────

const GOODS_META: Record<string, { label: string; color: string }> = {
  food_pack:   { label: "Food Pack",   color: "bg-orange-100 text-orange-800" },
  water:       { label: "Water",       color: "bg-blue-100 text-blue-800" },
  medicine:    { label: "Medicine",    color: "bg-red-100 text-red-800" },
  clothing:    { label: "Clothing",    color: "bg-purple-100 text-purple-800" },
  hygiene_kit: { label: "Hygiene Kit", color: "bg-green-100 text-green-800" },
  other:       { label: "Other",       color: "bg-gray-100 text-gray-700" },
};

const DISASTER_ICONS: Record<string, string> = {
  typhoon: "🌀", earthquake: "🌍", flood: "🌊",
  landslide: "⛰️", fire: "🔥",
};

// Score → color band for the priority score badge
function scoreColor(score: number): string {
  if (score >= 60) return "bg-red-100 text-red-800 border border-red-300";
  if (score >= 40) return "bg-orange-100 text-orange-800 border border-orange-300";
  if (score >= 20) return "bg-yellow-100 text-yellow-800 border border-yellow-300";
  return "bg-green-100 text-green-800 border border-green-300";
}

// Allocation status → badge style
const STATUS_STYLE: Record<string, string> = {
  recommended: "bg-blue-100 text-blue-800",
  approved:    "bg-green-100 text-green-800",
  dispatched:  "bg-purple-100 text-purple-800",
  delivered:   "bg-gray-100 text-gray-700",
  cancelled:   "bg-red-100 text-red-700",
};

const EMPTY_FORM = {
  goods_type: "food_pack",
  quantity: "",
  unit: "packs",
  source_name: "",
  warehouse_latitude: "10.3157",
  warehouse_longitude: "123.8854",
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function CoordinatorDashboard() {
  const { user, logout } = useAuth();

  // Event + supply state
  const [event, setEvent] = useState<DisasterEvent | null>(null);
  const [supplies, setSupplies] = useState<Supply[]>([]);
  const [loadingEvent, setLoadingEvent] = useState(true);
  const [loadingSupplies, setLoadingSupplies] = useState(false);

  // Log goods form state
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  // Allocation state
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [loadingAllocations, setLoadingAllocations] = useState(false);
  const [runningAllocation, setRunningAllocation] = useState(false);
  const [allocationError, setAllocationError] = useState("");

  // Tab state — "map" | "allocations"
  const [activeTab, setActiveTab] = useState<"map" | "allocations">("map");

  // ── Fetch active event on mount ────────────────────────────────────────────

  useEffect(() => {
    async function fetchEvent() {
      try {
        const res = await api.get("/events/", { params: { status: "active" } });
        if (res.data.length > 0) setEvent(res.data[0]);
      } catch (err) {
        console.error("Failed to fetch events", err);
      } finally {
        setLoadingEvent(false);
      }
    }
    fetchEvent();
  }, []);

  // ── Fetch supplies + existing allocations when event is known ──────────────

  useEffect(() => {
    if (!event) return;
    fetchSupplies();
    fetchAllocations();
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

  async function fetchAllocations() {
    if (!event) return;
    setLoadingAllocations(true);
    try {
      const res = await api.get(`/events/${event.id}/allocations`);
      setAllocations(res.data);
    } catch (err) {
      console.error("Failed to fetch allocations", err);
    } finally {
      setLoadingAllocations(false);
    }
  }

  // ── Run AI allocation ──────────────────────────────────────────────────────

  async function handleRunAllocation() {
    if (!event) return;
    setRunningAllocation(true);
    setAllocationError("");
    try {
      const res = await api.post(`/events/${event.id}/allocate`);
      setAllocations(res.data);
      // Switch to allocations tab automatically so coordinator sees the results
      setActiveTab("allocations");
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setAllocationError(
        typeof detail === "string" ? detail : "Allocation failed. Check that damage reports and supplies are logged."
      );
    } finally {
      setRunningAllocation(false);
    }
  }

  // ── Approve allocation ─────────────────────────────────────────────────────

  async function handleApprove(allocId: string) {
    if (!event) return;
    try {
      const res = await api.patch(`/events/${event.id}/allocations/${allocId}/approve`);
      // Update just the one row in state — no need to re-fetch everything
      setAllocations(prev =>
        prev.map(a => a.id === allocId ? { ...a, ...res.data } : a)
      );
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      alert(typeof detail === "string" ? detail : "Approve failed.");
    }
  }

  // ── Log goods form ─────────────────────────────────────────────────────────

  async function handleLogGoods(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setFormSuccess("");
    if (!form.source_name.trim()) { setFormError("Source name is required."); return; }
    if (!form.quantity || Number(form.quantity) <= 0) { setFormError("Quantity must be greater than 0."); return; }
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
      fetchSupplies();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setFormError(typeof detail === "string" ? detail : "Failed to log supply.");
    } finally {
      setSubmitting(false);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-PH", {
      month: "short", day: "numeric", year: "numeric",
    });
  }

  const supplyTotals = supplies.reduce<Record<string, number>>((acc, s) => {
    acc[s.goods_type] = (acc[s.goods_type] || 0) + s.quantity;
    return acc;
  }, {});

  // Group allocations by barangay for the table
  // Each barangay can have multiple rows (one per goods_type) —
  // we show them grouped so the coordinator reads it as one dispatch plan per barangay.
  const allocationsByBarangay = allocations.reduce<Record<string, Allocation[]>>(
    (acc, a) => {
      if (!acc[a.barangay_name]) acc[a.barangay_name] = [];
      acc[a.barangay_name].push(a);
      return acc;
    },
    {}
  );

  // Unique barangays sorted by priority_rank (take rank from first allocation row)
  const rankedBarangays = Object.entries(allocationsByBarangay).sort(
    ([, aRows], [, bRows]) => aRows[0].priority_rank - bRows[0].priority_rank
  );

  // ── Loading / empty states ─────────────────────────────────────────────────

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
          <p className="text-sm text-gray-400 mt-1">When an event is declared, it will appear here.</p>
          <button onClick={logout} className="mt-6 text-sm text-red-500 hover:underline">Sign out</button>
        </div>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-screen bg-gray-100 flex flex-col overflow-hidden">

      {/* ── Top nav ── */}
      <header className="bg-blue-800 text-white px-6 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold tracking-tight">ReliefMatch AI</span>
          <span className="text-blue-300 text-sm hidden sm:block">LGU Coordinator Dashboard</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-blue-200 hidden sm:block">{user?.full_name}</span>
          <button
            onClick={logout}
            className="text-sm bg-blue-700 hover:bg-blue-600 px-3 py-1.5 rounded-lg transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ── Main layout: sidebar + main panel ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── LEFT SIDEBAR ── */}
        <aside className="w-full max-w-sm bg-white border-r border-gray-200 flex flex-col overflow-y-auto">

          {/* Event header */}
          <div className="p-4 border-b border-gray-100 bg-red-50">
            <div className="flex items-start gap-3">
              <span className="text-3xl">{DISASTER_ICONS[event.disaster_type] ?? "⚠️"}</span>
              <div>
                <p className="font-bold text-gray-900 text-sm leading-tight">{event.name}</p>
                <p className="text-xs text-gray-500 mt-0.5">Declared {formatDate(event.declared_at)}</p>
                <span className="inline-block mt-1.5 text-xs font-semibold bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
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
                    <span key={type} className={`text-xs font-medium px-2.5 py-1 rounded-full ${meta.color}`}>
                      {meta.label}: {total.toLocaleString()}
                    </span>
                  );
                })}
              </div>
            )}
          </div>

          {/* Run AI Allocation button */}
          <div className="p-4 border-b border-gray-100">
            {allocationError && (
              <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-3">
                {allocationError}
              </p>
            )}
            <button
              onClick={handleRunAllocation}
              disabled={runningAllocation}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50
                         text-white text-sm font-semibold rounded-xl py-2.5 transition-colors mb-2"
            >
              {runningAllocation ? "⚙️ Running AI allocation…" : "🤖 Run AI Allocation"}
            </button>
            <p className="text-xs text-gray-400 text-center">
              Runs XGBoost scoring + OR-Tools routing
            </p>
          </div>

          {/* Log Goods button + form */}
          <div className="p-4 border-b border-gray-100">
            {formSuccess && (
              <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 mb-3">
                ✓ {formSuccess}
              </p>
            )}
            <button
              onClick={() => { setShowForm(!showForm); setFormError(""); setFormSuccess(""); }}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl py-2.5 transition-colors"
            >
              {showForm ? "✕ Cancel" : "+ Log Incoming Goods"}
            </button>
          </div>

          {showForm && (
            <form onSubmit={handleLogGoods} className="p-4 border-b border-gray-100 space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Goods Type</label>
                <select
                  value={form.goods_type}
                  onChange={e => setForm(f => ({ ...f, goods_type: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {Object.entries(GOODS_META).map(([val, { label }]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Quantity</label>
                  <input
                    type="number" min="1" required value={form.quantity}
                    onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))}
                    placeholder="e.g. 500"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Unit</label>
                  <select
                    value={form.unit}
                    onChange={e => setForm(f => ({ ...f, unit: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="packs">packs</option>
                    <option value="kg">kg</option>
                    <option value="liters">liters</option>
                    <option value="boxes">boxes</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Source / Donor</label>
                <input
                  type="text" required value={form.source_name}
                  onChange={e => setForm(f => ({ ...f, source_name: e.target.value }))}
                  placeholder="e.g. DSWD Region VII"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Warehouse Lat</label>
                  <input
                    type="number" step="0.0000001" value={form.warehouse_latitude}
                    onChange={e => setForm(f => ({ ...f, warehouse_latitude: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Warehouse Lng</label>
                  <input
                    type="number" step="0.0000001" value={form.warehouse_longitude}
                    onChange={e => setForm(f => ({ ...f, warehouse_longitude: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              {formError && (
                <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{formError}</p>
              )}
              <button
                type="submit" disabled={submitting}
                className="w-full bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-semibold rounded-xl py-2.5 transition-colors"
              >
                {submitting ? "Saving…" : "Save Supply Record"}
              </button>
            </form>
          )}

          {/* Supply inventory log */}
          <div className="p-4 flex-1">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Inventory Log</p>
            {loadingSupplies ? (
              <p className="text-xs text-gray-400">Loading…</p>
            ) : supplies.length === 0 ? (
              <p className="text-xs text-gray-400">No records yet.</p>
            ) : (
              <div className="space-y-2">
                {supplies.map(s => {
                  const meta = GOODS_META[s.goods_type] ?? GOODS_META.other;
                  return (
                    <div key={s.id} className="flex items-start justify-between bg-gray-50 rounded-xl px-3 py-2.5 text-xs">
                      <div>
                        <span className={`font-semibold px-1.5 py-0.5 rounded ${meta.color}`}>{meta.label}</span>
                        <p className="text-gray-500 mt-1 leading-tight">{s.source_name}</p>
                        <p className="text-gray-400">{formatDate(s.received_at)}</p>
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

        {/* ── RIGHT PANEL: tabbed ── */}
        <main className="flex-1 flex flex-col min-h-0 overflow-hidden">

          {/* Tab bar */}
          <div className="bg-white border-b border-gray-200 flex px-4 gap-1 pt-2">
            <button
              onClick={() => setActiveTab("map")}
              className={`px-4 py-2 text-sm font-semibold rounded-t-lg transition-colors
                ${activeTab === "map"
                  ? "bg-blue-50 text-blue-700 border-b-2 border-blue-600"
                  : "text-gray-500 hover:text-gray-700"}`}
            >
              🗺️ Map
            </button>
            <button
              onClick={() => setActiveTab("allocations")}
              className={`px-4 py-2 text-sm font-semibold rounded-t-lg transition-colors flex items-center gap-2
                ${activeTab === "allocations"
                  ? "bg-blue-50 text-blue-700 border-b-2 border-blue-600"
                  : "text-gray-500 hover:text-gray-700"}`}
            >
              🤖 Allocations
              {allocations.length > 0 && (
                <span className="bg-indigo-100 text-indigo-700 text-xs font-bold px-1.5 py-0.5 rounded-full">
                  {rankedBarangays.length}
                </span>
              )}
            </button>
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-hidden">

            {/* Map tab */}
            {activeTab === "map" && (
              <div className="h-full">
                <BarangayMap eventId={event.id} />
              </div>
            )}

            {/* Allocations tab */}
            {activeTab === "allocations" && (
              <div className="h-full overflow-y-auto p-4">

                {loadingAllocations && (
                  <p className="text-sm text-gray-400 text-center mt-8">Loading allocations…</p>
                )}

                {!loadingAllocations && allocations.length === 0 && (
                  <div className="text-center mt-16">
                    <p className="text-4xl mb-3">🤖</p>
                    <p className="font-semibold text-gray-700">No allocation plan yet</p>
                    <p className="text-sm text-gray-400 mt-1">
                      Click "Run AI Allocation" in the sidebar to generate a ranked dispatch plan.
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      Requires: damage reports filed + supply inventory logged.
                    </p>
                  </div>
                )}

                {!loadingAllocations && rankedBarangays.length > 0 && (
                  <div className="space-y-4 max-w-4xl mx-auto">
                    <div className="flex items-center justify-between mb-2">
                      <h2 className="text-sm font-semibold text-gray-700">
                        AI Dispatch Plan — {rankedBarangays.length} barangays
                      </h2>
                      <p className="text-xs text-gray-400">
                        Sorted by XGBoost priority score · Routing by OR-Tools CVRP
                      </p>
                    </div>

                    {rankedBarangays.map(([barangayName, rows]) => {
                      // All rows for a barangay share the same rank, score, explanation
                      const first = rows[0];
                      // Extract truck/stop from explanation string
                      const routeMatch = first.shap_explanation.match(/\[Truck (\d+), Stop (\d+)\]/);
                      const routeLabel = routeMatch
                        ? `Truck ${routeMatch[1]} · Stop ${routeMatch[2]}`
                        : null;
                      // Strip the routing suffix from the explanation for cleaner display
                      const explanationClean = first.shap_explanation
                        .replace(/\s*\[Truck \d+, Stop \d+\]/, "");

                      // Determine the overall status for this barangay
                      // (all goods rows share the same status after approve)
                      const overallStatus = first.status;
                      const canApprove = overallStatus === "recommended";

                      return (
                        <div
                          key={barangayName}
                          className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden"
                        >
                          {/* Barangay header row */}
                          <div className="flex items-start justify-between px-4 py-3 bg-gray-50 border-b border-gray-100">
                            <div className="flex items-center gap-3">
                              {/* Priority rank badge */}
                              <span className="w-7 h-7 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center flex-shrink-0">
                                {first.priority_rank}
                              </span>
                              <div>
                                <p className="font-semibold text-gray-900 text-sm">{barangayName}</p>
                                {routeLabel && (
                                  <p className="text-xs text-indigo-600 font-medium mt-0.5">
                                    🚛 {routeLabel}
                                  </p>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {/* Priority score badge */}
                              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${scoreColor(first.priority_score)}`}>
                                {first.priority_score.toFixed(0)}/100
                              </span>
                              {/* Status badge */}
                              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full capitalize ${STATUS_STYLE[overallStatus] ?? "bg-gray-100 text-gray-600"}`}>
                                {overallStatus}
                              </span>
                              {/* Approve button */}
                              {canApprove && (
                                <button
                                  onClick={() => handleApprove(first.id)}
                                  className="text-xs bg-green-600 hover:bg-green-700 text-white font-semibold px-3 py-1 rounded-lg transition-colors"
                                >
                                  Approve
                                </button>
                              )}
                            </div>
                          </div>

                          {/* SHAP explanation */}
                          <div className="px-4 py-2 border-b border-gray-50 bg-blue-50">
                            <p className="text-xs text-blue-800 leading-relaxed">
                              💡 {explanationClean}
                            </p>
                          </div>

                          {/* Goods allocation rows */}
                          <div className="divide-y divide-gray-50">
                            {rows.map(row => {
                              const meta = GOODS_META[row.goods_type] ?? GOODS_META.other;
                              return (
                                <div key={row.id} className="flex items-center justify-between px-4 py-2">
                                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${meta.color}`}>
                                    {meta.label}
                                  </span>
                                  <span className="text-sm font-bold text-gray-800">
                                    {row.quantity_allocated.toLocaleString()}
                                    <span className="text-xs font-normal text-gray-400 ml-1">units</span>
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}