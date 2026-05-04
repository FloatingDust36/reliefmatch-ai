// frontend/src/pages/DamageReportForm.tsx
//
// Mobile-first damage report submission form.
// Barangay officials open this on their phone while in the field.
// Design priorities: large tap targets, minimal typing, clear labels.
//
// Route: /portal/report/:eventId

import { useState, FormEvent } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../services/api";
import { useAuth } from "../context/AuthContext";

// Matches the damage_reports table columns
interface ReportFormData {
  population_affected: string;
  casualty_count: string;
  structures_damaged: string;
  structures_destroyed: string;
  road_accessibility: "accessible" | "partially_blocked" | "cut_off";
  has_power: boolean;
  has_water: boolean;
  hours_since_last_goods: string;
  goods_received_qty: string;
  special_needs_notes: string;
}

const INITIAL_FORM: ReportFormData = {
  population_affected: "",
  casualty_count: "0",
  structures_damaged: "0",
  structures_destroyed: "0",
  road_accessibility: "accessible",
  has_power: true,
  has_water: true,
  hours_since_last_goods: "",
  goods_received_qty: "0",
  special_needs_notes: "",
};

export default function DamageReportForm() {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const [form, setForm] = useState<ReportFormData>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const { user } = useAuth();

  const updateField = (field: keyof ReportFormData, value: any) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!user?.barangay_id) {
        setError("Your account is not assigned to a barangay. Contact your LGU coordinator.");
        return;
    }

    // Frontend validation — catch obvious errors before hitting the API
    if (!form.population_affected || Number(form.population_affected) < 1) {
      setError("Population affected must be at least 1.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post(`/events/${eventId}/reports`, {
        barangay_id: user.barangay_id,  // from JWT/auth context
        population_affected: Number(form.population_affected),
        casualty_count: Number(form.casualty_count),
        structures_damaged: Number(form.structures_damaged),
        structures_destroyed: Number(form.structures_destroyed),
        road_accessibility: form.road_accessibility,
        has_power: form.has_power,
        has_water: form.has_water,
        // If blank, send null — means "never received goods"
        hours_since_last_goods: form.hours_since_last_goods
          ? Number(form.hours_since_last_goods)
          : null,
        goods_received_qty: Number(form.goods_received_qty),
        special_needs_notes: form.special_needs_notes || null,
      });
      setSuccess(true);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : "Submission failed. Check your connection and try again."
      );
    } finally {
      setSubmitting(false);
    }
  };

  // Success screen — shown after submission
  if (success) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="text-center max-w-sm">
          <div className="text-5xl mb-4">✅</div>
          <h2 className="text-xl font-bold text-gray-900 mb-2">Report Submitted</h2>
          <p className="text-gray-500 text-sm mb-6">
            Your damage report has been received. The LGU coordinator will review
            it and generate an allocation plan.
          </p>
          <button
            onClick={() => navigate("/portal")}
            className="bg-blue-600 text-white rounded-xl px-6 py-3 font-semibold text-sm"
          >
            Back to Portal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sticky header — stays visible while scrolling the form */}
      <div className="sticky top-0 z-10 bg-blue-700 text-white px-4 py-3 shadow-md">
        <button
          onClick={() => navigate("/portal")}
          className="text-blue-200 text-sm mb-1 hover:text-white"
        >
          ← Back
        </button>
        <h1 className="text-lg font-bold">Damage Report</h1>
        <p className="text-blue-200 text-xs">Fill in current conditions in your barangay</p>
      </div>

      <form onSubmit={handleSubmit} className="max-w-lg mx-auto p-4 space-y-6 pb-24">

        {/* --- SECTION 1: Affected Population --- */}
        <section className="bg-white rounded-2xl p-4 shadow-sm">
          <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="text-blue-600">👥</span> Affected Population
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Residents affected <span className="text-red-500">*</span>
              </label>
              <input
                type="number"
                min="1"
                required
                value={form.population_affected}
                onChange={(e) => updateField("population_affected", e.target.value)}
                placeholder="e.g. 847"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-400 mt-1">
                Displaced or directly affected — not total barangay population
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Casualties (deaths + injuries)
              </label>
              <input
                type="number"
                min="0"
                value={form.casualty_count}
                onChange={(e) => updateField("casualty_count", e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </section>

        {/* --- SECTION 2: Structural Damage --- */}
        <section className="bg-white rounded-2xl p-4 shadow-sm">
          <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="text-orange-500">🏚️</span> Structural Damage
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Partially damaged
              </label>
              <input
                type="number"
                min="0"
                value={form.structures_damaged}
                onChange={(e) => updateField("structures_damaged", e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Totally destroyed
              </label>
              <input
                type="number"
                min="0"
                value={form.structures_destroyed}
                onChange={(e) => updateField("structures_destroyed", e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </section>

        {/* --- SECTION 3: Accessibility & Utilities --- */}
        <section className="bg-white rounded-2xl p-4 shadow-sm">
          <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="text-yellow-500">🚧</span> Access & Utilities
          </h2>

          {/* Road accessibility — big tap targets, not a tiny dropdown */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Road accessibility
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(
                [
                  { value: "accessible", label: "Clear", color: "green" },
                  { value: "partially_blocked", label: "Partial", color: "yellow" },
                  { value: "cut_off", label: "Cut Off", color: "red" },
                ] as const
              ).map(({ value, label, color }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => updateField("road_accessibility", value)}
                  className={`py-3 rounded-xl text-sm font-semibold border-2 transition-all
                    ${
                      form.road_accessibility === value
                        ? color === "green"
                          ? "bg-green-100 border-green-500 text-green-800"
                          : color === "yellow"
                          ? "bg-yellow-100 border-yellow-500 text-yellow-800"
                          : "bg-red-100 border-red-500 text-red-800"
                        : "bg-white border-gray-200 text-gray-600"
                    }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Power + Water — large toggle rows */}
          <div className="space-y-3">
            {(
              [
                { field: "has_power", label: "Has electricity", icon: "⚡" },
                { field: "has_water", label: "Has potable water", icon: "💧" },
              ] as const
            ).map(({ field, label, icon }) => (
              <div
                key={field}
                className="flex items-center justify-between py-2"
              >
                <span className="text-sm text-gray-700 flex items-center gap-2">
                  {icon} {label}
                </span>
                <button
                  type="button"
                  onClick={() => updateField(field, !form[field])}
                  className={`relative w-14 h-7 rounded-full transition-colors duration-200
                    ${form[field] ? "bg-blue-500" : "bg-gray-300"}`}
                >
                  <span
                    className={`absolute top-0.5 w-6 h-6 bg-white rounded-full shadow
                      transition-transform duration-200
                      ${form[field] ? "translate-x-7" : "translate-x-0.5"}`}
                  />
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* --- SECTION 4: Relief History --- */}
        <section className="bg-white rounded-2xl p-4 shadow-sm">
          <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="text-purple-500">📦</span> Relief Goods Status
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Hours since last goods received
              </label>
              <input
                type="number"
                min="0"
                value={form.hours_since_last_goods}
                onChange={(e) => updateField("hours_since_last_goods", e.target.value)}
                placeholder="Leave blank if never received"
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Total goods received this event (kg)
              </label>
              <input
                type="number"
                min="0"
                step="0.1"
                value={form.goods_received_qty}
                onChange={(e) => updateField("goods_received_qty", e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                           focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </section>

        {/* --- SECTION 5: Special Needs --- */}
        <section className="bg-white rounded-2xl p-4 shadow-sm">
          <h2 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <span className="text-pink-500">🆘</span> Special Needs
          </h2>
          <textarea
            rows={3}
            value={form.special_needs_notes}
            onChange={(e) => updateField("special_needs_notes", e.target.value)}
            placeholder="e.g. 12 pregnant women, 34 senior citizens, infants need formula"
            className="w-full border border-gray-300 rounded-xl px-4 py-3 text-base
                       focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <p className="text-xs text-gray-400 mt-1">
            This goes directly to the LGU coordinator's attention
          </p>
        </section>

        {/* Error message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* Submit — fixed to bottom on mobile */}
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 p-4">
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50
                       text-white font-bold rounded-xl py-4 text-base
                       transition-colors duration-150"
          >
            {submitting ? "Submitting…" : "Submit Damage Report"}
          </button>
        </div>
      </form>
    </div>
  );
}