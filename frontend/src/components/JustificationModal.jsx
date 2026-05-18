import React, { useState } from "react";

export default function JustificationModal({ open, title, onCancel, onConfirm, busy = false }) {
  const [reason, setReason] = useState("");

  if (!open) return null;

  const handleConfirm = () => {
    if (!reason.trim()) return;
    onConfirm?.(reason.trim());
    setReason("");
  };

  const handleCancel = () => {
    setReason("");
    onCancel?.();
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 20000,
        background: "rgba(0,0,0,0.65)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px",
      }}
    >
      <div
        style={{
          width: "min(560px, 100%)",
          background: "#0f172a",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "12px",
          padding: "16px",
          display: "flex",
          flexDirection: "column",
          gap: "10px",
        }}
      >
        <div style={{ fontSize: "14px", fontWeight: 800 }}>
          {title || "Justificacion requerida"}
        </div>
        <div style={{ fontSize: "12px", color: "rgba(255,255,255,0.82)" }}>
          Explica brevemente por que deseas continuar con esta excepcion.
        </div>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={5}
          placeholder="Escribe tu justificacion..."
          style={{
            background: "rgba(255,255,255,0.06)",
            color: "#fff",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: "8px",
            padding: "10px",
            resize: "vertical",
          }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
          <button
            type="button"
            disabled={busy}
            onClick={handleCancel}
            style={{
              border: "1px solid rgba(255,255,255,0.2)",
              background: "transparent",
              color: "#fff",
              borderRadius: "8px",
              padding: "8px 10px",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={busy || !reason.trim()}
            onClick={handleConfirm}
            style={{
              border: "1px solid rgba(16,185,129,0.6)",
              background: "rgba(16,185,129,0.25)",
              color: "#fff",
              borderRadius: "8px",
              padding: "8px 10px",
              cursor: busy || !reason.trim() ? "not-allowed" : "pointer",
            }}
          >
            Guardar justificacion
          </button>
        </div>
      </div>
    </div>
  );
}

