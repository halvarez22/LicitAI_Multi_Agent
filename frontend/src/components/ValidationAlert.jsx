import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

const MESSAGE_PREVIEW_CHARS = 380;

const severityStyle = {
  block: {
    border: "1px solid rgba(239,68,68,0.45)",
    bg: "rgba(239,68,68,0.08)",
    icon: "#f87171",
    tag: "ACCIÓN REQUERIDA",
  },
  warn: {
    border: "1px solid rgba(245,158,11,0.45)",
    bg: "rgba(245,158,11,0.08)",
    icon: "#f59e0b",
    tag: "SUGERENCIA",
  },
  info: {
    border: "1px solid rgba(56,189,248,0.45)",
    bg: "rgba(56,189,248,0.08)",
    icon: "#38bdf8",
    tag: "INFORMACIÓN",
  },
};

function SeverityIcon({ severity }) {
  if (severity === "block") return <AlertTriangle size={16} color={severityStyle.block.icon} />;
  if (severity === "warn") return <AlertTriangle size={16} color={severityStyle.warn.icon} />;
  return <Info size={16} color={severityStyle.info.icon} />;
}

export default function ValidationAlert({
  event,
  onPrimaryAction,
  onSecondaryAction,
  busy = false,
}) {
  const [expanded, setExpanded] = useState(false);
  const ux = event && typeof event === "object" ? event.ux || {} : {};
  const fullMessage =
    event && typeof event === "object"
      ? ux.user_message || event.meta?.raw_message || ""
      : "";
  const { preview, needsToggle } = useMemo(() => {
    const t = (fullMessage || "").trim();
    if (!t || t.length <= MESSAGE_PREVIEW_CHARS) {
      return { preview: t, needsToggle: false };
    }
    return {
      preview: `${t.slice(0, MESSAGE_PREVIEW_CHARS).trim()}…`,
      needsToggle: true,
    };
  }, [fullMessage]);
  useEffect(() => {
    setExpanded(false);
  }, [fullMessage]);
  if (!event || typeof event !== "object") return null;
  const severity = event.severity || "warn";
  const style = severityStyle[severity] || severityStyle.warn;
  const title = ux.title || event.error_type || "Validacion";
  const message = expanded ? (fullMessage || "").trim() : preview;
  const impact = ux.impact || "";

  return (
    <div
      style={{
        border: style.border,
        background: style.bg,
        borderRadius: "12px",
        padding: "12px",
        display: "flex",
        flexDirection: "column",
        gap: "8px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <SeverityIcon severity={severity} />
        <div style={{ fontSize: "11px", fontWeight: 800, letterSpacing: "0.5px", textTransform: 'uppercase' }}>
          {style.tag} • {title}
        </div>
      </div>
      {message ? (
        <div style={{ fontSize: "12px", lineHeight: 1.45, whiteSpace: "pre-wrap" }}>{message}</div>
      ) : null}
      {needsToggle ? (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          style={{
            alignSelf: "flex-start",
            border: "none",
            background: "transparent",
            color: "rgba(147,197,253,0.95)",
            fontSize: "11px",
            fontWeight: 700,
            cursor: "pointer",
            padding: 0,
            textDecoration: "underline",
          }}
        >
          {expanded ? "Mostrar menos" : "Mostrar todo"}
        </button>
      ) : null}
      {impact ? (
        <div style={{ fontSize: "11px", color: "rgba(255,255,255,0.8)" }}>
          <strong>Impacto:</strong> {impact}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
        {ux.primary_action ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onPrimaryAction?.(event)}
            style={{
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.08)",
              color: "#fff",
              fontSize: "11px",
              fontWeight: 700,
              borderRadius: "8px",
              padding: "7px 10px",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            {ux.primary_action.label || "Resolver"}
          </button>
        ) : null}
        {ux.secondary_action ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onSecondaryAction?.(event)}
            style={{
              border: "1px solid rgba(255,255,255,0.15)",
              background: "transparent",
              color: "rgba(255,255,255,0.9)",
              fontSize: "11px",
              fontWeight: 700,
              borderRadius: "8px",
              padding: "7px 10px",
              cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            {ux.secondary_action.label || "Accion secundaria"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

