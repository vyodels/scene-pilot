from __future__ import annotations

import pytest

from recruit_agent.agent_runtime.types import LLMRequest
from recruit_agent.core.settings import AppSettings
from recruit_agent.agent_runtime.providers import ProviderError
from recruit_agent.services.container import AppContainer


def test_functional_closure_real_provider_path_is_not_fake_default(tmp_path) -> None:
    container = AppContainer.build(
        AppSettings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite:///{tmp_path / 'functional-provider.db'}",
            provider_config={"openai_api_key": "", "anthropic_api_key": ""},
        )
    )
    assert container.provider.provider_name == "unavailable"
    with pytest.raises(ProviderError):
        container.provider.invoke(LLMRequest(id="req", turn_id="turn", invocation_id="inv", messages=[]))
