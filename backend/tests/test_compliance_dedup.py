"""
Tests para P0: Fingerprint canónico, Dedup global cross-zona, y reasignación de IDs.
Cubre: _canonical_item_fingerprint, _dedupe_master_list_categories, _is_better_item.
"""
from unittest.mock import MagicMock

import pytest

from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager


@pytest.fixture
def agent() -> ComplianceAgent:
    return ComplianceAgent(MagicMock(spec=MCPContextManager))


# ─── _canonical_item_fingerprint ─────────────────────────────────────────────

class TestCanonicalFingerprint:
    def test_same_snippet_same_fingerprint(self, agent: ComplianceAgent):
        """Ítems con snippet idéntico deben generar el mismo fingerprint."""
        a = {"snippet": "Será motivo de desechamiento de las proposiciones si..."}
        b = {"snippet": "Será motivo de desechamiento de las proposiciones si..."}
        assert agent._canonical_item_fingerprint(a) == agent._canonical_item_fingerprint(b)

    def test_different_snippets_different_fingerprint(self, agent: ComplianceAgent):
        """Ítems con snippets distintos deben generar fingerprints distintos."""
        a = {"snippet": "El licitante debe presentar fianza de cumplimiento"}
        b = {"snippet": "Se requiere póliza de responsabilidad civil vigente"}
        assert agent._canonical_item_fingerprint(a) != agent._canonical_item_fingerprint(b)

    def test_normalization_ignores_case_and_accents(self, agent: ComplianceAgent):
        """La normalización de texto (lowercase, sin acentos) produce el mismo fingerprint."""
        a = {"snippet": "GARANTÍA DE CUMPLIMIENTO del contrato según ARTÍCULO 48"}
        b = {"snippet": "garantia de cumplimiento del contrato segun articulo 48"}
        assert agent._canonical_item_fingerprint(a) == agent._canonical_item_fingerprint(b)

    def test_fallback_to_descripcion_when_snippet_short(self, agent: ComplianceAgent):
        """Si el snippet es muy corto (<15 chars), se usa descripcion."""
        a = {"snippet": "corto", "descripcion": "Presentar acta constitutiva original legalmente válida"}
        b = {"snippet": "", "descripcion": "Presentar acta constitutiva original legalmente válida"}
        assert agent._canonical_item_fingerprint(a) == agent._canonical_item_fingerprint(b)

    def test_fallback_to_nombre_when_all_empty(self, agent: ComplianceAgent):
        """Si snippet y descripcion están vacíos, se usa nombre."""
        a = {"snippet": "", "descripcion": "", "nombre": "Requisito de fianza"}
        fp = agent._canonical_item_fingerprint(a)
        assert isinstance(fp, str)
        assert len(fp) == 32  # SHA-256 truncado a 32 hex chars

    def test_fingerprint_length(self, agent: ComplianceAgent):
        """El fingerprint siempre mide 32 caracteres hex."""
        item = {"snippet": "Un snippet de prueba suficientemente largo para test"}
        fp = agent._canonical_item_fingerprint(item)
        assert len(fp) == 32
        assert all(c in "0123456789abcdef" for c in fp)


# ─── _is_better_item ────────────────────────────────────────────────────────

class TestIsBetterItem:
    def test_evidence_match_wins(self, agent: ComplianceAgent):
        """Un ítem con evidence_match=True gana sobre uno con False."""
        better = {"evidence_match": True, "match_tier": "none", "snippet": "x"}
        worse = {"evidence_match": False, "match_tier": "literal", "snippet": "x" * 100}
        assert agent._is_better_item(better, worse) is True
        assert agent._is_better_item(worse, better) is False

    def test_better_tier_wins_when_evidence_equal(self, agent: ComplianceAgent):
        """Si evidence_match es igual, gana el de mejor match_tier."""
        literal = {"evidence_match": True, "match_tier": "literal", "snippet": "x"}
        weak = {"evidence_match": True, "match_tier": "weak", "snippet": "x" * 200}
        assert agent._is_better_item(literal, weak) is True
        assert agent._is_better_item(weak, literal) is False

    def test_longer_snippet_wins_when_tier_equal(self, agent: ComplianceAgent):
        """Si evidence y tier son iguales, gana el de snippet más largo."""
        long_snip = {"evidence_match": True, "match_tier": "normalized", "snippet": "a" * 100}
        short_snip = {"evidence_match": True, "match_tier": "normalized", "snippet": "a" * 30}
        assert agent._is_better_item(long_snip, short_snip) is True
        assert agent._is_better_item(short_snip, long_snip) is False

    def test_tie_keeps_existing(self, agent: ComplianceAgent):
        """En empate total, se mantiene el existente (is_better devuelve False)."""
        a = {"evidence_match": True, "match_tier": "literal", "snippet": "mismo texto"}
        b = {"evidence_match": True, "match_tier": "literal", "snippet": "mismo texto"}
        assert agent._is_better_item(a, b) is False


# ─── _split_context ───────────────────────────────────────────────────────────

class TestSplitContext:
    def test_short_context_single_chunk(self, agent: ComplianceAgent):
        ctx = "a" * 100
        assert agent._split_context(ctx, 8000, 800) == [ctx]

    def test_long_context_covers_tail(self, agent: ComplianceAgent):
        """Todo el texto debe procesarse: antes solo se tomaban 2 bloques y el resto se perdía."""
        ctx = "A" * 5000 + "B" * 5000 + "C" * 5000 + "Z" * 5000
        chunks = agent._split_context(ctx, 8000, 800)
        # 20_000 chars, paso 7200 → 3 ventanas cubren hasta el final (no 2).
        assert len(chunks) >= 3
        assert chunks[-1][-1] == "Z"
        assert "Z" * 200 in chunks[-1]

    def test_chunk_size_zero_returns_whole(self, agent: ComplianceAgent):
        assert agent._split_context("abc", 0, 800) == ["abc"]


# ─── _dedupe_master_list_categories ──────────────────────────────────────────

class TestDedupeMasterList:
    def _make_item(self, snippet, zona="ADMIN", evidence=True, tier="normalized", cat="administrativo"):
        return {
            "id": "XX-00",
            "nombre": snippet[:30],
            "snippet": snippet,
            "descripcion": snippet,
            "evidence_match": evidence,
            "match_tier": tier,
            "zona_origen": zona,
            "categoria": cat,
            "page": 1,
            "seccion": "N/A",
            "quality_flags": [],
        }

    def test_duplicates_are_merged(self, agent: ComplianceAgent):
        """Dos ítems con el mismo fingerprint deben colapsar a uno."""
        master = {
            "administrativo": [
                self._make_item("Será motivo de desechamiento de las proposiciones si con posterioridad al acto"),
                self._make_item("Será motivo de desechamiento de las proposiciones si con posterioridad al acto"),
            ],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        assert len(result["administrativo"]) == 1

    def test_unique_items_are_preserved(self, agent: ComplianceAgent):
        """Ítems con distinto contenido no deben fusionarse."""
        master = {
            "administrativo": [
                self._make_item("Presentar acta constitutiva original"),
                self._make_item("Garantía de cumplimiento del contrato"),
                self._make_item("Poder notarial del representante legal"),
            ],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        assert len(result["administrativo"]) == 3

    def test_best_item_wins(self, agent: ComplianceAgent):
        """El ítem ganador debe ser el de mejor calidad (evidence > tier > longitud)."""
        weak = self._make_item(
            "Será motivo de desechamiento de las proposiciones si con posterioridad al acto",
            zona="GARANTÍAS", evidence=False, tier="none"
        )
        strong = self._make_item(
            "Será motivo de desechamiento de las proposiciones si con posterioridad al acto",
            zona="ADMIN", evidence=True, tier="literal"
        )
        master = {
            "administrativo": [weak, strong],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        winner = result["administrativo"][0]
        assert winner["evidence_match"] is True
        assert winner["match_tier"] == "literal"
        assert winner["zona_origen"] == "ADMIN"

    def test_ids_are_sequential_after_dedup(self, agent: ComplianceAgent):
        """Los IDs deben ser secuenciales: AD-01, AD-02, ..."""
        master = {
            "administrativo": [
                self._make_item("Primer requisito administrativo legal del contrato"),
                self._make_item("Primer requisito administrativo legal del contrato"),  # dup
                self._make_item("Segundo requisito distinto para la propuesta técnica"),
                self._make_item("Tercer requisito de la licitación pública nacional"),
            ],
            "tecnico": [
                self._make_item("Especificación técnica número uno del equipo", cat="tecnico"),
                self._make_item("Especificación técnica número dos del sistema", cat="tecnico"),
            ],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        admin_ids = [it["id"] for it in result["administrativo"]]
        assert admin_ids == ["AD-01", "AD-02", "AD-03"]

        tecnico_ids = [it["id"] for it in result["tecnico"]]
        assert tecnico_ids == ["TE-01", "TE-02"]

    def test_no_duplicate_ids_within_category(self, agent: ComplianceAgent):
        """No debe haber IDs repetidos dentro de una misma categoría."""
        items = [
            self._make_item(f"Requisito único número {i} con texto suficientemente largo")
            for i in range(15)
        ]
        master = {"administrativo": items, "tecnico": [], "formatos": []}
        result = agent._dedupe_master_list_categories(master)
        ids = [it["id"] for it in result["administrativo"]]
        assert len(ids) == len(set(ids)), f"IDs duplicados detectados: {ids}"

    def test_zonas_duplicadas_descartadas_tracked(self, agent: ComplianceAgent):
        """El ganador debe tener zonas_duplicadas_descartadas con la zona del perdedor."""
        item1 = self._make_item(
            "Será motivo de desechamiento de las proposiciones efectivas del licitante",
            zona="ADMIN", evidence=True, tier="literal"
        )
        item2 = self._make_item(
            "Será motivo de desechamiento de las proposiciones efectivas del licitante",
            zona="GARANTÍAS", evidence=False, tier="none"
        )
        master = {
            "administrativo": [item1, item2],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        winner = result["administrativo"][0]
        assert "zonas_duplicadas_descartadas" in winner
        assert "GARANTÍAS" in winner["zonas_duplicadas_descartadas"]

    def test_cross_zone_duplicates_within_same_category(self, agent: ComplianceAgent):
        """Ítems que vinieron de zonas distintas pero cayeron en la misma categoría."""
        from_admin = self._make_item(
            "El licitante deberá presentar carta compromiso bajo protesta de decir verdad",
            zona="ADMINISTATIVO/LEGAL"
        )
        from_garantias = self._make_item(
            "El licitante deberá presentar carta compromiso bajo protesta de decir verdad",
            zona="GARANTÍAS/SEGUROS"
        )
        master = {
            "administrativo": [from_admin, from_garantias],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        assert len(result["administrativo"]) == 1

    def test_empty_categories_are_safe(self, agent: ComplianceAgent):
        """Categorías vacías no causan error."""
        master = {"administrativo": [], "tecnico": [], "formatos": []}
        result = agent._dedupe_master_list_categories(master)
        assert result["administrativo"] == []
        assert result["tecnico"] == []
        assert result["formatos"] == []

    def test_non_dict_items_are_ignored(self, agent: ComplianceAgent):
        """Ítems no dict se ignoran sin error."""
        master = {
            "administrativo": [
                None,
                "basura",
                42,
                self._make_item("Requisito real y válido para la licitación pública nacional"),
            ],
            "tecnico": [],
            "formatos": [],
        }
        result = agent._dedupe_master_list_categories(master)
        assert len(result["administrativo"]) == 1
        assert result["administrativo"][0]["id"] == "AD-01"
