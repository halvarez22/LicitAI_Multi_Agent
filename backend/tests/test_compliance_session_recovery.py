from app.services.compliance_session_recovery import try_recover_compliance_master_list


def test_recover_from_mini_dictamen():
    state = {
        "mini_dictamen_anexos": {
            "items": [
                {
                    "canonical_id": "anexo_a",
                    "display_name": "Anexo A",
                    "category": "administrativo",
                    "source_filename": "anexo_a.doc",
                },
                {
                    "canonical_id": "prop_tec",
                    "display_name": "Propuesta técnica",
                    "category": "technical",
                },
            ]
        }
    }
    recovered, source = try_recover_compliance_master_list(state)
    assert source == "mini_dictamen_anexos"
    assert recovered
    assert len(recovered["administrativo"]) == 1
    assert len(recovered["tecnico"]) == 1
