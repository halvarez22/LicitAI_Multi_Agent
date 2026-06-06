export const PROFILE_DISPLAY_FIELDS = [
    'rfc',
    'razon_social',
    'representante_legal',
    'domicilio_fiscal',
    'objeto_social',
    'poderes',
];

export const formatProfileFieldValue = (value) => {
    if (value == null || value === '') return 'No detectado';
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed || 'No detectado';
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value);
    }
    if (Array.isArray(value)) {
        const lines = value
            .map((entry) => formatProfileFieldValue(entry))
            .filter((line) => line && line !== 'No detectado');
        return lines.length > 0 ? lines.join('\n') : 'No detectado';
    }
    if (typeof value === 'object') {
        const facultad = value.facultad ?? value.facultades ?? value.descripcion ?? value.poder;
        const fecha = value.fecha ?? value.vigencia ?? value.desde;
        if (facultad != null || fecha != null) {
            const parts = [];
            if (facultad != null && String(facultad).trim()) {
                parts.push(String(facultad).trim());
            }
            if (fecha != null && String(fecha).trim()) {
                parts.push(`(${String(fecha).trim()})`);
            }
            return parts.join(' ') || 'No detectado';
        }
        try {
            return JSON.stringify(value, null, 2);
        } catch {
            return 'No detectado';
        }
    }
    return String(value);
};

export const profileFieldHasContent = (value) => {
    if (value == null || value === '') return false;
    const formatted = formatProfileFieldValue(value);
    const normalized = formatted.trim().toLowerCase();
    return normalized.length > 0 && normalized !== 'no detectado' && normalized !== 'no encontrado';
};

export const hasMeaningfulMasterProfile = (profile) => {
    if (!profile) return false;
    return PROFILE_DISPLAY_FIELDS.some((field) => profileFieldHasContent(profile[field]));
};

export const normalizeMasterProfileForUi = (profile = {}) => {
    const normalized = { ...profile };
    for (const field of PROFILE_DISPLAY_FIELDS) {
        if (field in normalized && normalized[field] != null) {
            normalized[field] = formatProfileFieldValue(normalized[field]);
        }
    }
    return normalized;
};
