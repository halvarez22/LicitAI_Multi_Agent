/**
 * Formatea fecha_texto_raw del checklist para lectura en UI (evita párrafos completos de las bases).
 * @param {string|undefined|null} raw
 * @returns {string}
 */
const PLACEHOLDER_RE =
    /^(?:\.{3}|no especificado|no proporcionado|fecha\s+no\s+especificada|sin\s+fecha|n\/e|—|-)$/i;

/** @param {string} s */
function hasExtractableDate(s) {
    return (
        /\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñü]+\s+de\s+\d{4}/i.test(s) ||
        /\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}/i.test(s) ||
        /\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}/.test(s)
    );
}

/** @param {string} s */
function extractDateFragment(s) {
    const rangeCompact = s.match(
        /\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñü]+\s+de\s+\d{4}(?:\s*,?\s*\d{1,2}:\d{2}(?:[–\-]\d{1,2}:\d{2})?)?/i
    );
    if (rangeCompact) return rangeCompact[0].trim().replace(/\s+/g, ' ');

    const rangeNarrative = s.match(
        /los?\s+d[ií]as\s+\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñü]+\s+de\s+\d{4}[^.]*/i
    );
    if (rangeNarrative) return rangeNarrative[0].trim().replace(/\s+/g, ' ');

    const withTime = s.match(
        /\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}(?:\s*(?:,|\s+)?(?:a\s+las\s+)?\d{1,2}[:h]\d{2}(?:\s*(?:a\.?m\.?|p\.?m\.?|horas?)?)?)?/i
    );
    if (withTime) return withTime[0].trim().replace(/\s+/g, ' ');

    const dateOnly = s.match(/\d{1,2}\s+de\s+[a-záéíóúñü]+\s+(?:de|del)\s+\d{4}/i);
    if (dateOnly) return dateOnly[0].trim();

    const slash = s.match(
        /\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*\d{2,4}(?:\s+\d{1,2}[:h]\d{2})?/
    );
    if (slash) return slash[0].trim();
    return null;
}

/** @param {string} s */
function compactRangeFromText(s) {
    const m = String(s || '').match(
        /(\d{1,2})\s+y\s+(\d{1,2})\s+de\s+([a-záéíóúñü]+)\s+de\s+(\d{4})/i
    );
    if (!m) return null;
    const base = `${parseInt(m[1], 10)} y ${parseInt(m[2], 10)} de ${m[3]} de ${m[4]}`;
    const horario = String(s || '').match(/(\d{1,2}:\d{2})\s+a\s+(\d{1,2}:\d{2})/i);
    if (horario) return `${base}, ${horario[1]}–${horario[2]}`;
    return base;
}

/** @param {string} s */
function hasDayRange(s) {
    return /\d{1,2}\s+y\s+\d{1,2}\s+de\s+[a-záéíóúñü]+\s+de\s+\d{4}/i.test(String(s || ''));
}

export function formatFechaDisplay(raw) {
    const s = String(raw || '').trim();
    if (!s || PLACEHOLDER_RE.test(s)) {
        return 'Sin fecha en bases';
    }
    if (s.length <= 96 && hasExtractableDate(s)) {
        return s.replace(/\s+/g, ' ');
    }
    const extracted = extractDateFragment(s);
    if (extracted) return extracted;
    if (s.length > 140) return `${s.slice(0, 137).trim()}…`;
    return s;
}

/**
 * Fecha legible para un hito: usa fecha_texto_raw y, si hace falta, enriquece con bases_literal.
 * @param {{ fecha_texto_raw?: string, bases_literal?: string }|undefined|null} hito
 * @returns {string}
 */
export function formatHitoFechaDisplay(hito) {
    const raw = String(hito?.fecha_texto_raw || '').trim();
    const literal = String(hito?.bases_literal || '').trim();
    let display = formatFechaDisplay(raw);
    if (!hasDayRange(display) && literal) {
        const fromLiteral = compactRangeFromText(literal);
        if (fromLiteral) display = fromLiteral;
    }
    return display;
}

/** @param {string|undefined|null} raw */
export function fechaTieneValor(raw) {
    const s = String(raw || '').trim();
    if (!s || PLACEHOLDER_RE.test(s)) return false;
    return hasExtractableDate(s);
}
