/**
 * Formatea fecha_texto_raw del checklist para lectura en UI (evita párrafos completos de las bases).
 * @param {string|undefined|null} raw
 * @returns {string}
 */
export function formatFechaDisplay(raw) {
    const s = String(raw || '').trim();
    if (!s || s === '...' || /^no especificado$/i.test(s)) {
        return 'Sin fecha en bases';
    }
    const m = s.match(
        /\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}(?:\s+a\s+las\s+\d{1,2}:\d{2}(?:\s+horas?)?)?(?:\s*,\s*de\s+las\s+\d{1,2}:\d{2}[^.]*)?/i
    );
    if (m) return m[0].trim();
    const range = s.match(
        /los?\s+d[ií]as\s+\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}[^.]*/i
    );
    if (range) return range[0].trim().replace(/\s+/g, ' ');
    if (s.length > 140) return `${s.slice(0, 137).trim()}…`;
    return s;
}

/** @param {string|undefined|null} raw */
export function fechaTieneValor(raw) {
    const d = formatFechaDisplay(raw);
    return d !== 'Sin fecha en bases';
}
