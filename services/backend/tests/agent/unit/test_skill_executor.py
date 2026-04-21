from __future__ import annotations

from pathlib import Path

from recruit_agent.core.settings import AppSettings
from recruit_agent.db.session import create_engine_from_settings, create_session_factory, initialize_database
from recruit_agent.models.domain import Skill
from recruit_agent.skills.executor import build_invoke_skill_handler, execute_skill


def _make_session_factory(tmp_path: Path):
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'skill-executor.db'}",
    )
    engine = create_engine_from_settings(settings)
    initialize_database(engine)
    return create_session_factory(engine)


def test_execute_skill_runs_python_inline_artifact() -> None:
    skill = Skill(
        id="skill-1",
        skill_id="candidate-greeting",
        name="候选人打招呼",
        execution_hints={"executor_mode": "python_inline"},
        body={
            "summary": "生成首轮沟通文案。",
            "artifacts": {
                "python_inline": {
                    "entrypoint": "run",
                    "code": (
                        "def run(payload, context):\n"
                        "    candidate_name = payload.get('candidate_name') or '候选人'\n"
                        "    jd_title = payload.get('jd_title') or '目标岗位'\n"
                        "    return {\n"
                        "        'status': 'completed',\n"
                        "        'message': f'你好 {candidate_name}，我正在推进 {jd_title}，方便发下简历吗？',\n"
                        "        'skill': context['skill_id'],\n"
                        "    }\n"
                    ),
                }
            },
        },
    )

    result = execute_skill(skill, {"candidate_name": "张三", "jd_title": "算法工程师"})

    assert result["executor_mode"] == "python_inline"
    assert result["result"]["status"] == "completed"
    assert result["result"]["skill"] == "candidate-greeting"
    assert "张三" in result["result"]["message"]
    assert "算法工程师" in result["result"]["message"]


def test_build_invoke_skill_handler_loads_skill_from_registry(tmp_path: Path) -> None:
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as session:
        session.add(
            Skill(
                skill_id="resume-signal-parser",
                name="候选人回复信号分类",
                execution_hints={"executor_mode": "python_inline"},
                body={
                    "artifacts": {
                        "python_inline": {
                            "code": (
                                "def run(payload, context):\n"
                                "    text = str(payload.get('message') or '').lower()\n"
                                "    if '微信' in str(payload.get('message') or ''):\n"
                                "        return {'signal': 'wechat_requested', 'skill': context['skill_id']}\n"
                                "    if '电话' in str(payload.get('message') or ''):\n"
                                "        return {'signal': 'phone_requested', 'skill': context['skill_id']}\n"
                                "    return {'signal': 'unknown', 'normalized': text, 'skill': context['skill_id']}\n"
                            )
                        }
                    }
                },
            )
        )
        session.commit()

    handler = build_invoke_skill_handler(session_factory)
    result = handler({"skill_id": "resume-signal-parser", "input": {"message": "可以先留个微信吗？"}})

    assert result["executor_mode"] == "python_inline"
    assert result["result"]["signal"] == "wechat_requested"
    assert result["result"]["skill"] == "resume-signal-parser"
