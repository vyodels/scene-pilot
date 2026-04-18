from __future__ import annotations

from scene_pilot.memory.service import MemoryService


class ShortTermMemory:
    def __init__(self, service: MemoryService) -> None:
        self.service = service
