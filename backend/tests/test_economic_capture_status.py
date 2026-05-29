from app.services.economic_capture_matrix_service import economic_capture_status


def test_capture_complete_after_import():
    state = {
        "capture_matrix_blocks": [
            {
                "matrix_rows": [
                    {"field": "f1", "label": "A"},
                    {"field": "f2", "label": "B"},
                ]
            }
        ],
        "economic_user_inputs": {"f1": 10.0, "f2": 20.0},
        "pending_questions": [],
    }
    cap = economic_capture_status(state)
    assert cap["capture_complete"] is True
    assert cap["filled"] == 2


def test_capture_complete_inputs_only_without_matrix_blocks():
    """Tras import Excel, la sesión puede conservar solo economic_user_inputs."""
    inputs = {f"eco_{i}": float(i) for i in range(12)}
    state = {
        "capture_matrix_blocks": [],
        "economic_user_inputs": inputs,
        "pending_questions": [],
    }
    cap = economic_capture_status(state)
    assert cap["capture_complete"] is True
    assert cap["filled"] == 12
    assert cap["total"] == 12
