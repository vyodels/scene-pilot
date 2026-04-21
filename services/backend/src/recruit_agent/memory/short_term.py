from __future__ import annotations

from recruit_agent.memory.service import MemoryService


class ShortTermMemory:
    def __init__(self, service: MemoryService) -> None:
        self.service = service
