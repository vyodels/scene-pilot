from __future__ import annotations

from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import AgentDefinition
from recruit_agent.services.container import _seed_builtin_agent_definitions


def test_seed_builtin_definitions_normalizes_memory_writeback_policy(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-agent-seed.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(
            AgentDefinition(
                definition_key="recruit-agent",
                name="Recruit Agent",
                is_primary=True,
                prompt_config={},
                memory_policy={
                    "legacy_candidate_context": {"schema": ["legacy_business_context"]},
                    "legacy_job_context": {"schema": ["legacy_business_context"]},
                    "legacy_global_context": {"schema": ["legacy_business_context"]},
                    "writeback": {"auto_write_min_confidence": 0.9, "max_stable_facts": 3},
                },
            )
        )
        session.commit()

    _seed_builtin_agent_definitions(session_factory)

    with session_factory() as session:
        definition = session.query(AgentDefinition).filter_by(definition_key="recruit-agent").one()
        assert set(definition.memory_policy) == {"writeback"}
        assert definition.memory_policy["writeback"]["auto_write_min_confidence"] == 0.9
        assert definition.memory_policy["writeback"]["max_stable_facts"] == 3
        assert set(definition.product_bindings) == {"assistant", "autonomous"}


def test_seed_builtin_definitions_do_not_backfill_legacy_instruction_templates(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-agent-instruction-contract.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(
            AgentDefinition(
                definition_key="recruit-agent",
                name="Recruit Agent",
                is_primary=True,
                prompt_config={},
                memory_policy={},
            )
        )
        session.commit()

    _seed_builtin_agent_definitions(session_factory)

    with session_factory() as session:
        definition = session.query(AgentDefinition).filter_by(definition_key="recruit-agent").one()
        prompt_config = dict(definition.prompt_config or {})
        role_definition = dict(definition.role_definition or {})
        assert "instruction_template" not in prompt_config
        assert "instructionTemplate" not in prompt_config
        assert "automation_instruction" not in role_definition
        assert "automationInstruction" not in role_definition
