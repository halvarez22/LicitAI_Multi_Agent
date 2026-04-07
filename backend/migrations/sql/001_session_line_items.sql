-- Partidas tabulares (Excel) por sesión/documento. Ejecutar en Postgres si no usáis SQLAlchemy create_all.
-- Idempotente: solo crea si no existe.

CREATE TABLE IF NOT EXISTS session_line_items (
    id VARCHAR NOT NULL PRIMARY KEY,
    session_id VARCHAR NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    document_id VARCHAR NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_type VARCHAR NOT NULL DEFAULT 'document_tabular',
    concepto_raw TEXT NOT NULL,
    concepto_norm VARCHAR NOT NULL,
    unidad VARCHAR,
    cantidad DOUBLE PRECISION,
    precio_unitario DOUBLE PRECISION NOT NULL,
    moneda VARCHAR NOT NULL DEFAULT 'MXN',
    sheet_name VARCHAR,
    row_index DOUBLE PRECISION,
    extra JSONB DEFAULT '{}'::jsonb,
    extraction_version VARCHAR NOT NULL DEFAULT '1',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS ix_session_line_items_session_id ON session_line_items (session_id);
CREATE INDEX IF NOT EXISTS ix_session_line_items_document_id ON session_line_items (document_id);
CREATE INDEX IF NOT EXISTS ix_session_line_items_concepto_norm ON session_line_items (concepto_norm);
