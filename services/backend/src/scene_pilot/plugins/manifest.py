from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from scene_pilot.plugins.host import PluginHost


class PluginManifest(Protocol):
    namespace: str

    def install(self, plugin_host: "PluginHost") -> None: ...


@dataclass(slots=True)
class StaticPluginManifest:
    namespace: str
    installer: Callable[["PluginHost"], None]

    def install(self, plugin_host: "PluginHost") -> None:
        self.installer(plugin_host)
