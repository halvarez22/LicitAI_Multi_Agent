/**
 * Construye TSV para pegar en Excel desde bloques de capture_matrix_blocks.
 * Debe coincidir con backend format_matrix_blocks_excel_tsv.
 */
export function buildMatrixExcelTsv(blocks) {
    if (!Array.isArray(blocks) || blocks.length === 0) return '';

    const lines = [];
    let priceTitle = 'Precio unitario (sin IVA)';

    const cell = (v) =>
        String(v ?? '')
            .replace(/\t/g, ' ')
            .replace(/\r?\n/g, ' ')
            .trim();

    for (const block of blocks) {
        const cols = block.matrix_columns || [
            { key: 'label', title: 'Zona / horario / ubicación' },
            { key: 'price', title: block.column_label || priceTitle },
        ];
        let labelKey = 'label';
        let priceKey = 'price';
        for (const c of cols) {
            if (c.key === 'label') labelKey = c.key;
            else if (c.key) priceKey = c.key;
        }
        const priceCol = cols.find((c) => c.key === priceKey);
        if (priceCol?.title) priceTitle = priceCol.title;

        const source = cell(block.source_file || block.intro_message || 'anexo');
        if (lines.length === 0) {
            lines.push(['Anexo / archivo', 'Concepto / ubicación', priceTitle].join('\t'));
        }
        for (const row of block.matrix_rows || []) {
            lines.push([source, cell(row[labelKey]), cell(row[priceKey])].join('\t'));
        }
    }
    return `\ufeff${lines.join('\n')}`;
}
