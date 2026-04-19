from typing import Any

__all__ = ["AppContainer"]


def __getattr__(name: str) -> Any:
    if name == "AppContainer":
        from .container import AppContainer

        return AppContainer
    raise AttributeError(name)
