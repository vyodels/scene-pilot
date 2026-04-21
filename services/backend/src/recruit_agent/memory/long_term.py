from __future__ import annotations

from recruit_agent.memory.service import MemoryService


class LongTermMemory:
    def __init__(self, service: MemoryService) -> None:
        self.service = service
