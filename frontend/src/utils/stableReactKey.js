/**
 * Keys estables para listas React (evita colisiones por slug truncado o ids repetidos).
 */

function hashString(input) {
    const text = String(input ?? '');
    let hash = 5381;
    for (let i = 0; i < text.length; i += 1) {
        hash = ((hash << 5) + hash) ^ text.charCodeAt(i);
    }
    return (hash >>> 0).toString(36);
}

function normalizeToken(value) {
    return String(value ?? '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_|_$/g, '');
}

/**
 * @param {object} opts
 * @param {string} opts.prefix - Namespace del panel (p. ej. candidate, fmt, forensic).
 * @param {string} [opts.scope] - Sección o categoría visible.
 * @param {number} opts.index - Índice en la lista renderizada.
 * @param {object} [opts.item] - Objeto de fila.
 * @param {string[]} [opts.identityFields] - Campos usados para huella estable.
 */
export function buildStableReactKey({
    prefix,
    scope = '',
    index,
    item = {},
    identityFields = ['id', 'document_id', 'nombre_canonico', 'nombre', 'numero_anexo', 'page', 'tipo'],
}) {
    const parts = identityFields
        .map((field) => {
            const value = item?.[field];
            if (value == null || value === '') return '';
            return `${field}:${String(value)}`;
        })
        .filter(Boolean);
    const fingerprint = hashString(parts.join('|') || `row-${index}`);
    const scopeToken = normalizeToken(scope) || 'default';
    return `${prefix}-${scopeToken}-${index}-${fingerprint}`;
}

export default buildStableReactKey;
