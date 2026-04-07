/**
 * Base URL de la API. En Docker + Vite se usa `/api/v1` y el proxy reenvía al backend.
 * Si VITE_API_URL es absoluta (http...), se usa tal cual (p. ej. entorno sin proxy).
 */
const raw = import.meta.env.VITE_API_URL;
export const API_BASE =
    raw && String(raw).startsWith('http') ? String(raw).replace(/\/$/, '') : (raw || '/api/v1').replace(/\/$/, '');
