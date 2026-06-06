/**
 * Formatea fecha_texto_raw del checklist para lectura en UI (evita párrafos completos de las bases).
 * @param {string|undefined|null} raw
 * @returns {string}
 */
const PLACEHOLDER_RE =
    /^(?:\.{3}|no especificado|fecha\s+no\s+especificada|sin\s+fecha|n\/e|—|-)$/i;

/** @param {string} s */
function hasExtractableDate(s) {
    return (
        /\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}/i.test(s) ||
        /\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}/.test(s)
    );
}

/** @param {string} s */
function extractDateFragment(s) {
    const withTime = s.match(
        /\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}(?:\s*(?:,|\s+)?(?:a\s+las\s+)?\d{1,2}[:h]\d{2}(?:\s*(?:a\.?m\.?|p\.?m\.?|horas?)?)?)?/i
    );
    if (withTime) return withTime[0].trim().replace(/\s+/g, ' ');
    const dateOnly = s.match(/\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}/i);
    if (dateOnly) return dateOnly[0].trim();
    const range = s.match(
        /los?\s+d[ií]as\s+\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñü]+\s+de\s+\d{4}[^.]*/i
    );
    if (range) return range[0].trim().replace(/\s+/g, ' ');
    const slash = s.match(
        /\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}(?:\s+\d{1,2}[:h]\d{2})?/
    );
    if (slash) return slash[0].trim();
    return null;
}

export function formatFechaDisplay(raw) {
    const s = String(raw || '').trim();
    if (!s || PLACEHOLDER_RE.test(s)) {
        return 'Sin fecha en bases';
    }
    const extracted = extractDateFragment(s);
    if (extracted) return extracted;
    if (s.length > 140) return `${s.slice(0, 137).trim()}…`;
    return s;
}

/** @param {string|undefined|null} raw */
export function fechaTieneValor(raw) {
    const s = String(raw || '').trim();
    if (!s || PLACEHOLDER_RE.test(s)) return false;
    return hasExtractableDate(s);
}
