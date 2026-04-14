import time

from fastapi.testclient import TestClient

from scene_pilot.core.app import create_app
from scene_pilot.core.settings import AppSettings, FeatureFlags
from scene_pilot.models import Candidate, Skill, Workflow


def test_autonomy_loop_disabled_by_default(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
        )
    )

    with TestClient(app) as client:
        autonomy = client.app.state.autonomy_loop
        assert autonomy.enabled is False
        assert autonomy.is_running() is False


def test_autonomy_loop_processes_enqueued_task_when_enabled(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
            feature_flags=FeatureFlags(enable_autonomy=True),
        )
    )
    container = app.state.bootstrap_container
    with container.session_factory() as session:
        candidate = Candidate(
            name="Autonomy Candidate",
            platform="boss",
            platform_candidate_id="boss_autonomy_001",
            status="screening",
        )
        workflow = Workflow(
            name="One Step Workflow",
            status="active",
            config={
                "start_node_id": "initial_screening",
                "nodes": [
                    {
                        "id": "initial_screening",
                        "name": "Initial Screening",
                        "task_type": "initial_screening",
                    }
                ],
            },
        )
        session.add_all([candidate, workflow])
        session.commit()
        session.refresh(candidate)
        session.refresh(workflow)

    container.agent_control.enqueue_task(
        "initial_screening",
        candidate_id=candidate.id,
        workflow_id=workflow.id,
        workflow_node_id="initial_screening",
        payload={"jd_criteria": "Python"},
        priority=250,
    )

    with TestClient(app) as client:
        autonomy = client.app.state.autonomy_loop
        assert autonomy.enabled is True
        assert autonomy.is_running() is True

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if container.scheduler.history and client.get("/api/agent").json()["queueDepth"] == 0:
                break
            time.sleep(0.05)

        assert container.scheduler.history
        assert container.scheduler.history[0].result.status == "completed"
        assert client.get("/api/agent").json()["queueDepth"] == 0

    assert app.state.autonomy_loop.is_running() is False


def test_autonomy_loop_runs_periodic_skill_health_sweep(tmp_path):
    app = create_app(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'scene-pilot.db'}",
            feature_flags=FeatureFlags(enable_autonomy=True, enable_skill_health_autonomy=True),
            skill_health_autonomy_interval_seconds=1,
        )
    )
    container = app.state.bootstrap_container
    with container.session_factory() as session:
        skill = Skill(
            skill_id="autonomy-health-skill",
            name="Autonomy Health Skill",
            status="active",
            platform="runtime-scene",
            strategy={"prompt": "screen"},
            health_check_config={"required_strategy_keys": ["prompt", "rubric"]},
        )
        session.add(skill)
        session.commit()

    with TestClient(app) as client:
        autonomy = client.app.state.autonomy_loop
        assert autonomy.enabled is True
        assert autonomy.health_sweep_enabled is True

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with container.session_factory() as session:
                refreshed = session.query(Skill).filter(Skill.skill_id == "autonomy-health-skill").first()
                if refreshed is not None and refreshed.status == "degraded":
                    break
            time.sleep(0.05)

        with container.session_factory() as session:
            refreshed = session.query(Skill).filter(Skill.skill_id == "autonomy-health-skill").first()
            assert refreshed is not None
            assert refreshed.status == "degraded"
            assert refreshed.last_health_status == "warning"

        assert any(event.source == "skill_health" for event in container.events.snapshot())
