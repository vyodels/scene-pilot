from __future__ import annotations

from collections.abc import Iterable

from recruit_agent.plugins.host import PluginHost
from recruit_agent.plugins.manifest import PluginManifest


def install_manifest(host: PluginHost, manifest: PluginManifest) -> None:
    manifest.install(host)


def install_manifests(host: PluginHost, manifests: Iterable[PluginManifest]) -> None:
    for manifest in manifests:
        install_manifest(host, manifest)
