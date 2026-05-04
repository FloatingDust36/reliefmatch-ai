// frontend/src/components/BarangayMap.tsx
//
// Leaflet map showing all barangays for an active disaster event.
// Markers are color-coded by urgency derived from damage report data.
// Clicking a marker OR a sidebar row syncs the selection both ways.
//
// Urgency is computed client-side from damage report fields until
// Week 6 when the XGBoost model produces real priority_score values.
// The urgency logic here mirrors the same feature weights the ML model uses,
// so the visual is already meaningful — not just placeholder colors.
//
// Color scale:
//   Red    — cut off roads OR zero goods ever received
//   Orange — partially blocked OR >72 hrs since last goods
//   Yellow — accessible but >24 hrs since last goods
//   Green  — accessible + goods received recently

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import api from "../services/api";

// ── Fix Leaflet default marker icon paths broken by Vite bundling ─────────────
// Vite hashes asset filenames — Leaflet's internal URL builder doesn't know that.
// We override it once here so every marker in the app works correctly.
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

// ── Types ─────────────────────────────────────────────────────────────────────

interface DamageReport {
  id: string;
  barangay_id: string;
  population_affected: number;
  casualty_count: number;
  structures_damaged: number;
  structures_destroyed: number;
  road_accessibility: "accessible" | "partially_blocked" | "cut_off";
  has_power: boolean;
  has_water: boolean;
  hours_since_last_goods: number | null;
  goods_received_qty: number;
  special_needs_notes: string | null;
}

interface Barangay {
  id: string;
  name: string;
  population: number;
  latitude: number;
  longitude: number;
  poverty_incidence_pct: number | null;
}

// Merged view — one entry per barangay that has a damage report
interface BarangayStatus extends Barangay {
  report: DamageReport;
  urgency: "red" | "orange" | "yellow" | "green";
  urgencyLabel: string;
}

// ── Urgency Logic ─────────────────────────────────────────────────────────────
// Pre-ML heuristic that matches the XGBoost feature priorities from Doc 5.1.
// When Week 6 lands, replace this with the priority_score from the allocations API.

function computeUrgency(r: DamageReport): {
  urgency: "red" | "orange" | "yellow" | "green";
  urgencyLabel: string;
} {
  if (
    r.road_accessibility === "cut_off" ||
    r.hours_since_last_goods === null  // never received goods
  ) {
    return { urgency: "red", urgencyLabel: "Critical" };
  }
  if (
    r.road_accessibility === "partially_blocked" ||
    (r.hours_since_last_goods !== null && r.hours_since_last_goods > 72)
  ) {
    return { urgency: "orange", urgencyLabel: "High" };
  }
  if (r.hours_since_last_goods !== null && r.hours_since_last_goods > 24) {
    return { urgency: "yellow", urgencyLabel: "Moderate" };
  }
  return { urgency: "green", urgencyLabel: "Stable" };
}

// ── Marker Colors ─────────────────────────────────────────────────────────────

const URGENCY_COLOR: Record<string, string> = {
  red: "#ef4444",
  orange: "#f97316",
  yellow: "#eab308",
  green: "#22c55e",
};

function makeCircleMarker(urgency: string) {
  return L.divIcon({
    className: "",
    html: `
      <div style="
        width: 20px; height: 20px;
        background: ${URGENCY_COLOR[urgency]};
        border: 3px solid white;
        border-radius: 50%;
        box-shadow: 0 2px 6px rgba(0,0,0,0.35);
      "></div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    popupAnchor: [0, -12],
  });
}

function makeCircleMarkerSelected(urgency: string) {
  return L.divIcon({
    className: "",
    html: `
      <div style="
        width: 26px; height: 26px;
        background: ${URGENCY_COLOR[urgency]};
        border: 4px solid white;
        border-radius: 50%;
        box-shadow: 0 0 0 3px ${URGENCY_COLOR[urgency]}, 0 2px 8px rgba(0,0,0,0.4);
      "></div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -15],
  });
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  eventId: string;
}

export default function BarangayMap({ eventId }: Props) {
  const mapRef = useRef<L.Map | null>(null);
  const mapDivRef = useRef<HTMLDivElement>(null);
  const markersRef = useRef<Record<string, L.Marker>>({});

  const [barangays, setBarangays] = useState<BarangayStatus[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // ── Fetch damage reports + barangay details ──────────────────────────────

  useEffect(() => {
    async function load() {
      try {
        // Step 1: get all damage reports for this event
        const reportsRes = await api.get(`/events/${eventId}/reports`);
        const reports: DamageReport[] = reportsRes.data;

        if (reports.length === 0) {
          setLoading(false);
          return;
        }

        // Step 2: get barangay list for the coordinator's LGU
        // We derive lgu_id from the first report's barangay lookup.
        // GET /lgus/{lgu_id}/barangays — but we need lgu_id first.
        // Shortcut: fetch each barangay individually via the event's LGU.
        // The coordinator's lgu_id is in their JWT — we read it from localStorage.
        const storedUser = localStorage.getItem("user");
        const user = storedUser ? JSON.parse(storedUser) : null;
        if (!user?.lgu_id) {
          setLoading(false);
          return;
        }

        const brgyRes = await api.get(`/lgus/${user.lgu_id}/barangays`);
        const allBarangays: Barangay[] = brgyRes.data;

        // Step 3: join reports to barangays
        const reportMap: Record<string, DamageReport> = {};
        for (const r of reports) {
          reportMap[r.barangay_id] = r;
        }

        const statuses: BarangayStatus[] = [];
        for (const b of allBarangays) {
          const report = reportMap[b.id];
          if (!report) continue; // Only show barangays that filed a report
          const { urgency, urgencyLabel } = computeUrgency(report);
          statuses.push({ ...b, report, urgency, urgencyLabel });
        }

        // Sort: red first, then orange, yellow, green
        const order = { red: 0, orange: 1, yellow: 2, green: 3 };
        statuses.sort((a, b) => order[a.urgency] - order[b.urgency]);

        setBarangays(statuses);
      } catch (err) {
        console.error("Failed to load map data", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [eventId]);

  // ── Initialize Leaflet map ───────────────────────────────────────────────

  useEffect(() => {
    if (!mapDivRef.current || mapRef.current) return;

    mapRef.current = L.map(mapDivRef.current, {
      center: [10.3157, 123.8854], // Cebu City
      zoom: 13,
      zoomControl: true,
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(mapRef.current);

    // Force Leaflet to recalculate container size after flex layout settles
    setTimeout(() => mapRef.current?.invalidateSize(), 300);

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [loading]);

  // ── Add/update markers when barangay data loads ──────────────────────────

  useEffect(() => {
    if (!mapRef.current || barangays.length === 0) return;

    // Clear old markers
    Object.values(markersRef.current).forEach(m => m.remove());
    markersRef.current = {};

    for (const b of barangays) {
      const marker = L.marker([b.latitude, b.longitude], {
        icon: makeCircleMarker(b.urgency),
      });

      // Popup content
      const hoursText =
        b.report.hours_since_last_goods === null
          ? "Never received"
          : `${b.report.hours_since_last_goods} hrs ago`;

      marker.bindPopup(`
        <div style="font-family: sans-serif; min-width: 180px;">
          <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px;">
            ${b.name}
          </div>
          <div style="
            display: inline-block;
            background: ${URGENCY_COLOR[b.urgency]}22;
            color: ${URGENCY_COLOR[b.urgency]};
            border: 1px solid ${URGENCY_COLOR[b.urgency]};
            border-radius: 999px;
            padding: 1px 8px;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 8px;
          ">
            ${b.urgencyLabel.toUpperCase()}
          </div>
          <table style="font-size: 12px; width: 100%; border-collapse: collapse;">
            <tr><td style="color:#6b7280; padding: 2px 0;">Affected</td>
                <td style="font-weight:600; text-align:right;">
                  ${b.report.population_affected.toLocaleString()} people
                </td></tr>
            <tr><td style="color:#6b7280; padding: 2px 0;">Casualties</td>
                <td style="font-weight:600; text-align:right;">
                  ${b.report.casualty_count}
                </td></tr>
            <tr><td style="color:#6b7280; padding: 2px 0;">Road</td>
                <td style="font-weight:600; text-align:right;">
                  ${b.report.road_accessibility.replace("_", " ")}
                </td></tr>
            <tr><td style="color:#6b7280; padding: 2px 0;">Last goods</td>
                <td style="font-weight:600; text-align:right;">${hoursText}</td></tr>
            <tr><td style="color:#6b7280; padding: 2px 0;">Power</td>
                <td style="font-weight:600; text-align:right;">
                  ${b.report.has_power ? "✓ Yes" : "✗ No"}
                </td></tr>
            <tr><td style="color:#6b7280; padding: 2px 0;">Water</td>
                <td style="font-weight:600; text-align:right;">
                  ${b.report.has_water ? "✓ Yes" : "✗ No"}
                </td></tr>
          </table>
          ${b.report.special_needs_notes ? `
            <div style="
              margin-top: 8px; padding: 6px 8px;
              background: #fef3c7; border-radius: 6px;
              font-size: 11px; color: #92400e;
            ">
              ⚠️ ${b.report.special_needs_notes}
            </div>` : ""}
        </div>
      `, { maxWidth: 260 });

      marker.on("click", () => {
        setSelected(b.id);
      });

      marker.addTo(mapRef.current!);
      markersRef.current[b.id] = marker;
    }

    // Fit map bounds to all markers
    const coords = barangays.map(b => [b.latitude, b.longitude] as L.LatLngTuple);
    mapRef.current.fitBounds(L.latLngBounds(coords), { padding: [40, 40] });

    // Tiles won't paint if Leaflet measured the container before flex settled.
    // Force a recalculate now that markers and bounds are set.
    setTimeout(() => mapRef.current?.invalidateSize(), 50);

  }, [barangays]);

  // ── Sync marker icon when selection changes ──────────────────────────────

  useEffect(() => {
    for (const [id, marker] of Object.entries(markersRef.current)) {
      const b = barangays.find(x => x.id === id);
      if (!b) continue;
      marker.setIcon(
        id === selected
          ? makeCircleMarkerSelected(b.urgency)
          : makeCircleMarker(b.urgency)
      );
    }

    // Pan to selected marker
    if (selected && markersRef.current[selected]) {
      const b = barangays.find(x => x.id === selected);
      if (b) {
        mapRef.current?.panTo([b.latitude, b.longitude], { animate: true });
        markersRef.current[selected].openPopup();
      }
    }
  }, [selected, barangays]);

  // ── Sidebar click handler ────────────────────────────────────────────────

  function handleSidebarClick(id: string) {
    setSelected(id);
  }

  // ── Legend ───────────────────────────────────────────────────────────────

  const legendItems = [
    { color: "red",    label: "Critical — cut off / no goods ever" },
    { color: "orange", label: "High — partial access / >72 hrs" },
    { color: "yellow", label: "Moderate — accessible / >24 hrs" },
    { color: "green",  label: "Stable — goods received recently" },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <p className="text-gray-400 text-sm">Loading map data…</p>
      </div>
    );
  }

  if (barangays.length === 0) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center">
          <p className="text-2xl mb-2">🗺️</p>
          <p className="text-gray-500 text-sm font-medium">
            No damage reports filed yet
          </p>
          <p className="text-gray-400 text-xs mt-1">
            Barangay officials must submit reports before the map populates.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full">

      {/* ── Barangay sidebar list ── */}
      <div className="w-56 bg-white border-r border-gray-200 overflow-y-auto
                      flex flex-col flex-shrink-0">
        <div className="p-3 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Barangays ({barangays.length})
          </p>
        </div>
        <div className="flex-1">
          {barangays.map(b => (
            <button
              key={b.id}
              onClick={() => handleSidebarClick(b.id)}
              className={`w-full text-left px-3 py-3 border-b border-gray-50
                          hover:bg-gray-50 transition-colors
                          ${selected === b.id ? "bg-blue-50 border-l-4 border-l-blue-500" : ""}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ background: URGENCY_COLOR[b.urgency] }}
                />
                <span className="text-xs font-semibold text-gray-800 leading-tight">
                  {b.name}
                </span>
              </div>
              <div className="ml-4 mt-0.5 text-xs text-gray-400">
                {b.report.population_affected.toLocaleString()} affected
              </div>
            </button>
          ))}
        </div>

        {/* Legend */}
        <div className="p-3 border-t border-gray-100 bg-gray-50">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Legend
          </p>
          {legendItems.map(({ color, label }) => (
            <div key={color} className="flex items-start gap-2 mb-1.5">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5"
                style={{ background: URGENCY_COLOR[color] }}
              />
              <span className="text-xs text-gray-500 leading-tight">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Leaflet map ── */}
      <div ref={mapDivRef} className="flex-1 z-0 h-full" />
    </div>
  );
}