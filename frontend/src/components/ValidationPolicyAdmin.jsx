import React, { useEffect, useState } from "react";
import axios from "axios";
import { API_BASE } from "../apiBase.js";

const PRESETS = {
  strict: {
    label: "Estricto (Gubernamental)",
    policy: {
      allow_skip_with_justification: false,
      error_type_overrides: {
        precios_positivos: { allow_skip_with_justification: false },
        missing_mandatory_field: { allow_skip_with_justification: false },
        signature_pending: { allow_skip_with_justification: false },
        consistencia_subtotales: { allow_skip_with_justification: false },
      },
    },
  },
  flexible: {
    label: "Flexible (Comercial)",
    policy: {
      allow_skip_with_justification: true,
      error_type_overrides: {
        precios_positivos: { allow_skip_with_justification: false },
      },
    },
  },
};

export default function ValidationPolicyAdmin({ sessionId }) {
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("custom");
  const [jsonValue, setJsonValue] = useState("{\n  \n}");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [lastChange, setLastChange] = useState(null);

  useEffect(() => {
    if (!sessionId) return;
    (async () => {
      try {
        setLoading(true);
        const res = await axios.get(
          `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-policy`
        );
        const data = res?.data?.data || {};
        const policy = data.validation_policy || {};
        setJsonValue(JSON.stringify(policy, null, 2) || "{\n  \n}");
        const hist = Array.isArray(data.history) ? data.history : [];
        if (hist.length > 0) setLastChange(hist[hist.length - 1]);
      } catch (err) {
        console.warn("No se pudo cargar validation_policy:", err);
      } finally {
        setLoading(false);
      }
    })();
  }, [sessionId]);

  const applyPreset = (key) => {
    setPreset(key);
    if (key === "custom") return;
    const def = PRESETS[key];
    if (!def) return;
    setJsonValue(JSON.stringify(def.policy, null, 2));
  };

  const handleSave = async () => {
    if (!sessionId) return;
    let parsed;
    try {
      parsed = JSON.parse(jsonValue);
      if (parsed === null || typeof parsed !== "object") {
        alert("La política debe ser un objeto JSON.");
        return;
      }
    } catch (e) {
      alert("JSON inválido. Corrige el formato antes de guardar.");
      return;
    }
    const reason = window.prompt(
      "Describe brevemente el motivo del cambio de política (se guardará para auditoría):"
    );
    if (!reason || !reason.trim()) return;
    try {
      setSaving(true);
      const res = await axios.put(
        `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-policy`,
        {
          policy: parsed,
          reason: reason.trim(),
          updated_by: "ui-admin",
        }
      );
      const data = res?.data?.data || {};
      if (data.last_change) setLastChange(data.last_change);
      alert("Política de validación actualizada.");
    } catch (err) {
      console.error("Error guardando validation_policy:", err);
      alert("No se pudo guardar la política. Revisa la consola/logs.");
    } finally {
      setSaving(false);
    }
  };

  if (!sessionId) return null;

  return (
    <div
      style={{
        marginTop: "10px",
        paddingTop: "10px",
        borderTop: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          padding: "8px 10px",
          borderRadius: "10px",
          border: "1px dashed rgba(148,163,184,0.7)",
          background: "rgba(15,23,42,0.7)",
          color: "#e5e7eb",
          fontSize: "11px",
          fontWeight: 700,
          cursor: "pointer",
        }}
      >
        {open ? "▲ Política de validación (cerrar)" : "⚙ Política de validación (admin)"}
      </button>
      {open && (
        <div
          style={{
            marginTop: "8px",
            padding: "8px",
            borderRadius: "10px",
            background: "rgba(15,23,42,0.9)",
            border: "1px solid rgba(148,163,184,0.5)",
            display: "flex",
            flexDirection: "column",
            gap: "6px",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#9ca3af" }}>
              Preset
            </span>
            <select
              value={preset}
              onChange={(e) => applyPreset(e.target.value)}
              style={{
                flex: "1 1 auto",
                padding: "4px 6px",
                borderRadius: "8px",
                border: "1px solid rgba(148,163,184,0.7)",
                background: "rgba(15,23,42,0.9)",
                color: "#e5e7eb",
                fontSize: "11px",
              }}
            >
              <option value="custom">Custom (JSON libre)</option>
              {Object.entries(PRESETS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
          <textarea
            value={jsonValue}
            onChange={(e) => {
              setPreset("custom");
              setJsonValue(e.target.value);
            }}
            rows={8}
            spellCheck={false}
            style={{
              width: "100%",
              resize: "vertical",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas",
              fontSize: "11px",
              background: "rgba(15,23,42,0.95)",
              color: "#e5e7eb",
              borderRadius: "8px",
              border: "1px solid rgba(31,41,55,0.9)",
              padding: "8px",
            }}
          />
          <button
            type="button"
            disabled={loading || saving}
            onClick={handleSave}
            style={{
              alignSelf: "flex-end",
              padding: "6px 10px",
              borderRadius: "8px",
              border: "1px solid rgba(16,185,129,0.7)",
              background: "rgba(16,185,129,0.15)",
              color: "#bbf7d0",
              fontSize: "11px",
              fontWeight: 700,
              cursor: loading || saving ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "Guardando..." : "Guardar política"}
          </button>
          {lastChange && (
            <div style={{ fontSize: "10px", color: "#9ca3af" }}>
              Último cambio por <strong>{lastChange.updated_by}</strong> en{" "}
              {lastChange.updated_at}
              <br />
              Motivo: <em>{lastChange.reason}</em>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

