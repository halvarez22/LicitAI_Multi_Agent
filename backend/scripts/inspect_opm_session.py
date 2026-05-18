"""
Inspecciona y limpia la sesión OPM-001-2026 MADERA CHIHUAHUA.

Elimina:
1. Pendientes economic_price que son documentos de obra pública (no llevan PU)
2. Pendientes de intake sin field/label que son preguntas de acción ya obsoletas
3. El bloqueo de calidad documental si el usuario quiere omitirlo

Uso:
  python scripts/inspect_opm_session.py           # solo inspeccionar
  python scripts/inspect_opm_session.py --apply   # aplicar limpieza
  python scripts/inspect_opm_session.py --apply --clear-quality-block  # también limpiar bloqueo calidad
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.factory import MemoryAdapterFactory
from app.services.economic_cotization_filters import is_contaminated_economic_pending_question

SESSION_ID = "licitacion_opm-001-2026_madera_chihuahua"
DRY_RUN = "--apply" not in sys.argv
CLEAR_QUALITY = "--clear-quality-block" in sys.argv


def _is_stale_intake_action(q: dict) -> bool:
    """
    True si el pendiente es una pregunta de acción del intake (INTAKE-A-*) sin field/label.
    Estas preguntas son instrucciones de acción, no preguntas de datos — no deben
    quedarse bloqueando el flujo conversacional.
    También elimina pendientes con field genérico como 'profile_field_N'.
    """
    qid = str(q.get("question_id") or "")
    q_type = str(q.get("question_type") or "")
    field = str(q.get("field") or "").strip()
    label = str(q.get("label") or "").strip()
    # INTAKE-A-* son preguntas de acción (no de datos)
    if qid.startswith("INTAKE-A-") and not field and not label:
        return True
    # question_type="A" sin field también son acciones
    if q_type == "A" and not field and not label:
        return True
    # Pendientes con field genérico como 'profile_field_N' son residuos del loop
    import re
    if field and re.match(r"^profile_field_\d+$", field):
        return True
    # Pendientes con field_target técnico sin label legible (formato viejo)
    field_target = str(q.get("field_target") or "").strip()
    if field_target and not label and field_target == field:
        return True
    return False


async def main():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    state = await memory.get_session(SESSION_ID)
    if not state:
        print(f"ERROR: Sesión no encontrada: {SESSION_ID}")
        return

    pending = list(state.get("pending_questions") or [])
    print(f"Total pendientes: {len(pending)}\n")

    keep = []
    removed_contaminated = []
    removed_stale_intake = []
    removed_quality = []
    seen_question_ids = {}  # Para deduplicar por question_id

    for q in pending:
        qid = str(q.get("question_id") or "")
        q_type_field = str(q.get("type") or "")

        # 1. Pendientes económicos contaminados (documentos de obra pública)
        if is_contaminated_economic_pending_question(q):
            removed_contaminated.append(q)
            continue

        # 2. Preguntas de acción del intake sin field/label o con field genérico
        if _is_stale_intake_action(q):
            removed_stale_intake.append(q)
            continue

        # 3. Bloqueo de calidad documental (opcional)
        if CLEAR_QUALITY and (
            q_type_field == "document_quality_gate_blocking"
            or str(q.get("field") or "") == "document_quality_gate"
        ):
            removed_quality.append(q)
            continue

        # 4. Deduplicar por question_id — mantener el que tiene label más limpio
        if qid:
            if qid in seen_question_ids:
                # Comparar: preferir el que tiene label legible (no técnico)
                existing = seen_question_ids[qid]
                existing_label = str(existing.get("label") or "")
                new_label = str(q.get("label") or "")
                # Si el nuevo tiene label más limpio (sin puntos técnicos), reemplazar
                if "." not in new_label and "." in existing_label:
                    keep.remove(existing)
                    seen_question_ids[qid] = q
                    keep.append(q)
                # Si el existente ya es limpio, descartar el nuevo
                continue
            seen_question_ids[qid] = q

        keep.append(q)

    print(f"Pendientes económicos contaminados a eliminar ({len(removed_contaminated)}):")
    for r in removed_contaminated:
        print(f"  - {r.get('label', '')[:80]}")

    print(f"\nPreguntas de acción intake obsoletas a eliminar ({len(removed_stale_intake)}):")
    for r in removed_stale_intake:
        qid = r.get('question_id', '')
        q_preview = str(r.get('question') or '')[:80]
        print(f"  - [{qid}] {q_preview}")

    if CLEAR_QUALITY:
        print(f"\nBloqueos de calidad a eliminar ({len(removed_quality)}):")
        for r in removed_quality:
            print(f"  - {r.get('label', r.get('question_id', ''))[:80]}")

    print(f"\nA MANTENER ({len(keep)}):")
    for k in keep:
        qid = k.get('question_id', '')
        label = k.get('label') or k.get('question', '')
        print(f"  + [{k.get('type') or k.get('question_type')}] {qid} {str(label)[:70]}")

    total_removed = len(removed_contaminated) + len(removed_stale_intake) + len(removed_quality)
    print(f"\nResumen: {len(pending)} -> {len(keep)} pendientes (eliminados {total_removed})")

    if DRY_RUN:
        print("\n[DRY-RUN] No se escribió nada.")
        print("Usa --apply para aplicar, o --apply --clear-quality-block para también limpiar el bloqueo de calidad.")
    else:
        new_idx = min(int(state.get("current_question_index") or 0), max(0, len(keep) - 1))
        state["pending_questions"] = keep
        state["current_question_index"] = new_idx

        # Limpiar hints de bloqueo si se eliminaron todos los pendientes de calidad
        if CLEAR_QUALITY and removed_quality:
            state.pop("last_document_quality_waiting_hints", None)
            state.pop("last_document_fill_quality_waiting_hints", None)

        await memory.save_session(SESSION_ID, state)
        print(f"\n[APLICADO] Sesión actualizada. Pendientes: {len(pending)} -> {len(keep)}")
        if len(keep) == 0:
            print("Cola vacía — el chatbot debería desbloquearse para generación.")
        else:
            print(f"Próximo pendiente: [{keep[0].get('type') or keep[0].get('question_type')}] "
                  f"{keep[0].get('question_id', '')} "
                  f"{str(keep[0].get('label') or keep[0].get('question', ''))[:60]}")

    await memory.disconnect()


asyncio.run(main())
