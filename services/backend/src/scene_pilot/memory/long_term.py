from __future__ import annotations

from scene_pilot.memory.service import MemoryService


class LongTermMemory:
    def __init__(self, service: MemoryService) -> None:
        self.service = service
