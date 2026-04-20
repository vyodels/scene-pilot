from __future__ import annotations

import pytest

from scene_pilot.core.settings import AppSettings
from scene_pilot.repositories.domain import SettingsRepository
from scene_pilot.runtime.models import Message
from scene_pilot.runtime.providers import ProviderError
from scene_pilot.services.container import AppContainer


def test_container_uses_explicit_unavailable_provider_without_credentials(tmp_path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'container-provider.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)

    assert container.provider.provider_name == "unavailable"
    with pytest.raises(ProviderError, match="provider unavailable"):
        container.provider.generate([Message(role="user", content="hello")])


def test_container_uses_real_provider_registry_when_credentials_exist(tmp_path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'container-provider-real.db'}",
        provider_config={
            "openai_api_key": "test-key",
            "openai_base_url": "http://127.0.0.1:8317/v1",
        },
    )
    container = AppContainer.build(settings)

    assert container.provider.provider_name == "provider_registry"


def test_container_build_hydrates_persisted_provider_settings(tmp_path) -> None:
    settings = AppSettings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite:///{tmp_path / 'container-provider-persisted.db'}",
        provider_config={},
    )
    container = AppContainer.build(settings)
    with container.session_factory() as session:
        persisted = settings.model_dump()
        persisted["provider_config"] = {
            "openai_api_key": "persisted-test-key",
            "openai_base_url": "http://127.0.0.1:8317/v1",
            "openai_model": "gpt-5.4",
        }
        SettingsRepository(session).save(persisted)

    reloaded = AppContainer.build(settings)
    assert reloaded.provider.provider_name == "provider_registry"
