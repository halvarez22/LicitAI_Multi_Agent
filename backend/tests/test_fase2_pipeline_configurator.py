"""
tests/test_fase2_pipeline_configurator.py
Pruebas unitarias para el motor de configuración del pipeline adaptativo.
"""
import pytest
from app.orchestration.pipeline_configurator import PipelineConfigurator, PipelineType, ActionType

def test_configurator_chooses_light_for_low_complexity():
    profile = {"complexity": "low", "is_cost_focus": False}
    config = PipelineConfigurator.configure(profile)
    
    assert config.pipeline_type == PipelineType.ANALYSIS_LIGHT
    # En ANALYSIS_LIGHT, 'technical' se salta (según la lógica definida)
    assert "technical" not in config.stages
    assert "analysis" in config.stages

def test_configurator_chooses_cost_focus():
    profile = {"complexity": "medium", "is_cost_focus": True}
    config = PipelineConfigurator.configure(profile)
    
    assert config.pipeline_type == PipelineType.COST_FOCUS
    assert "economic" in config.stages
    assert "economic_writer" in config.stages

def test_configurator_fallback_to_full():
    # Perfil vacío o complejo
    profile = {"complexity": "high", "is_cost_focus": False}
    config = PipelineConfigurator.configure(profile)
    
    assert config.pipeline_type == PipelineType.DEFAULT_FULL
    assert "technical" in config.stages
    assert "economic" in config.stages

def test_short_circuit_rules_generated():
    profile = {"complexity": "medium"}
    # Con confidence summary, se genera la regla de LOW_CONFIDENCE_AVG
    config = PipelineConfigurator.configure(profile, confidence_summary={"avg": 0.5})
    
    rule_names = [r.name for r in config.short_circuit_rules]
    assert any("low avg confidence" in n.lower() for n in rule_names)
    assert any("critical data" in n.lower() for n in rule_names)

def test_action_type_is_strongly_typed():
    # Validar que usemos enums y no strings libres propensos a errores
    from app.orchestration.pipeline_configurator import ShortCircuitRule, ConditionType
    rule = ShortCircuitRule(
        name="Test",
        condition_type=ConditionType.LOW_CONFIDENCE_AVG,
        threshold=0.5,
        action=ActionType.STOP
    )
    assert rule.action == ActionType.STOP
