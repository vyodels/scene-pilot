from __future__ import annotations

from pathlib import Path

from recruit_station.core.settings import AppSettings
from recruit_station.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_station.models.domain import AgentDefinition
from recruit_station.agents.autonomous import _definition_system_prompt
from recruit_station.services.container import _seed_builtin_agent_definitions


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
                definition_key="recruit-station",
                name="RecruitStation",
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
        definition = session.query(AgentDefinition).filter_by(definition_key="recruit-station").one()
        assert set(definition.memory_policy) == {"writeback"}
        assert definition.memory_policy["writeback"]["auto_write_min_confidence"] == 0.9
        assert definition.memory_policy["writeback"]["max_stable_facts"] == 3
        assert set(definition.product_bindings) == {"assistant", "autonomous", "jd_sync"}


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
                definition_key="recruit-station",
                name="RecruitStation",
                is_primary=True,
                prompt_config={},
                memory_policy={},
            )
        )
        session.commit()

    _seed_builtin_agent_definitions(session_factory)

    with session_factory() as session:
        definition = session.query(AgentDefinition).filter_by(definition_key="recruit-station").one()
        prompt_config = dict(definition.prompt_config or {})
        role_definition = dict(definition.role_definition or {})
        assert "instruction_template" not in prompt_config
        assert "instructionTemplate" not in prompt_config
        assert "automation_instruction" not in role_definition
        assert "automationInstruction" not in role_definition


def test_seed_builtin_definitions_preserves_saved_product_config(tmp_path: Path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'builtin-agent-product-config.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add(
            AgentDefinition(
                definition_key="recruit-station",
                name="RecruitStation",
                is_primary=True,
                prompt_config={},
                memory_policy={},
                product_bindings={
                    "autonomous": {"session_key": "custom-autonomous-session"},
                },
                product_config={
                    "jd_sync": {
                        "jd_sync_config": {
                            "executionSop": {
                                "siteEntryUrl": "https://mock-recruiting.local/jobs",
                                "siteAccessRulesText": "用户保存的入口边界",
                            },
                        },
                    },
                    "autonomous": {
                        "automation_recruiting_config": {
                            "executionSop": {
                                "siteEntryUrl": "https://mock-recruiting.local/jobs",
                                "stepsText": "用户保存的执行 SOP",
                            },
                            "defaultRunJobIds": ["jd-user"],
                        },
                    },
                },
                product_projections={
                    "autonomous": {"name": "用户命名的自动化招聘"},
                },
            )
        )
        session.commit()

    _seed_builtin_agent_definitions(session_factory)

    with session_factory() as session:
        definition = session.query(AgentDefinition).filter_by(definition_key="recruit-station").one()
        assert definition.product_bindings["autonomous"]["session_key"] == "custom-autonomous-session"
        assert "assistant" in definition.product_bindings
        assert definition.product_config["jd_sync"]["jd_sync_config"]["executionSop"]["siteEntryUrl"] == "https://mock-recruiting.local/jobs"
        assert definition.product_config["jd_sync"]["jd_sync_config"]["executionSop"]["siteAccessRulesText"] == "用户保存的入口边界"
        assert "可恢复异常只能作为下一步恢复策略的输入" in definition.product_config["jd_sync"]["prompt_config"]["system_prompt"]
        assert definition.product_config["autonomous"]["automation_recruiting_config"]["executionSop"]["siteEntryUrl"] == "https://mock-recruiting.local/jobs"
        assert definition.product_config["autonomous"]["automation_recruiting_config"]["executionSop"]["stepsText"] == "用户保存的执行 SOP"
        assert definition.product_config["autonomous"]["automation_recruiting_config"]["defaultRunJobIds"] == ["jd-user"]
        assert definition.product_config["assistant"]["prompt_config"]
        assert definition.product_projections["autonomous"]["name"] == "用户命名的自动化招聘"
        assert "assistant" in definition.product_projections


def test_runtime_system_prompt_uses_product_prompt_config_for_jd_sync() -> None:
    definition = AgentDefinition(
        definition_key="recruit-station",
        name="RecruitStation",
        is_primary=True,
        prompt_config={"system_prompt": "默认招聘执行提示词：必须通过 VirtualHID 做页面动作。"},
        product_config={
            "jd_sync": {
                "prompt_config": {
                    "system_prompt": "JD 同步 Agent 专用提示词：必须进入职位详情，列表不能算完成。",
                },
            },
        },
    )

    jd_sync_prompt = _definition_system_prompt(definition, agent_kind="jd_sync")
    autonomous_prompt = _definition_system_prompt(definition, agent_kind="autonomous")

    assert "JD 同步 Agent 专用提示词" in jd_sync_prompt
    assert "必须进入职位详情" in jd_sync_prompt
    assert "不得把本轮作为成功终局" in jd_sync_prompt
    assert "delegate_scene_context 返回部分结果" in jd_sync_prompt
    assert "不得主动聚焦浏览器地址栏、输入 URL 或粘贴 URL" in jd_sync_prompt
    assert "Cmd+L 聚焦地址栏" not in jd_sync_prompt
    assert "继续调用 scene 完成剩余职位" in jd_sync_prompt
    assert "必须通过 VirtualHID 做页面动作" in jd_sync_prompt
    assert autonomous_prompt == "默认招聘执行提示词：必须通过 VirtualHID 做页面动作。"
