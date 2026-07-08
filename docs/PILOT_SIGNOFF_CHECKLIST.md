# Checklist sign-off — Piloto on-premise HRU

**Cliente / operador:** ______________________  
**Fecha:** ______________________  
**Sesión de prueba:** ______________________ (ID genérico, no obligatorio ISAPEG)

Marque cada ítem tras validación en entorno on-premise. Criterios alineados a [`SPEC_DUAL_STREAM_GENERATION_AND_CHAT_COPILOT_COMPLETO_HRU.md`](SPEC_DUAL_STREAM_GENERATION_AND_CHAT_COPILOT_COMPLETO_HRU.md) §4.6–4.7.

---

## Funcional — copiloto y generación (F1–F10)

- [ ] **Cotización solo por chat** — precios capturados sin Excel obligatorio
- [ ] **Totales en chat (F8)** — tras captura se muestra resumen de totales sin códigos internos
- [ ] **Copiloto técnico (F9)** — metodología/personal capturados con `provenance_ui`
- [ ] **Estado dual** — consulta «cómo vamos técnica y económica» responde en un solo mensaje
- [ ] **Económica sin técnica** — modo `economic` genera sobre 3 sin `TechnicalWriter`
- [ ] **Técnica sin precios** — modo `technical` completa técnica + admin con tarifas diferidas (warning, no bloqueo)
- [ ] **Streams paralelos (F6)** — técnica y económica en colas independientes sin borrar el otro output
- [ ] **Empaquetado parcial** — manifiesto con `coverage_status: partial` y banner UI honesto
- [ ] **Trazabilidad de precios** — `provenance_ui` visible (chat vs Excel)
- [ ] **UX limpia** — ningún mensaje al usuario con `INCOMPLETE_*`, `MISSING_*`, `Gate 12.1`

---

## Operación

- [ ] Smoke F10 verde: `python scripts/smoke_pilot_onprem_hru.py`
- [ ] Sub-smokes verdes: `smoke_technical_chat_capture.py`, `smoke_isapeg_dual_copilot_e2e.py`
- [ ] Flags piloto documentados en `.env` (playbook §8–§9)
- [ ] Equipo capacitado con [`GUIA_PILOTO_ONPREM_HRU.md`](GUIA_PILOTO_ONPREM_HRU.md) (3 flujos)

---

## Post-piloto (opcional — producción estricta)

- [ ] `PACKAGING_REQUIRE_ALL_SOBRES=true` acordado con convocante
- [ ] `ADMIN_ECONOMIC_DEFERRAL=false` solo si bases exigen tarifa en admin (modo enforce)

---

**Firma operador LicitAI:** ______________________  
**Firma cliente:** ______________________
