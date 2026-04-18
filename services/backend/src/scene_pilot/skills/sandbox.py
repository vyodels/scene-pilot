from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar


ResultT = TypeVar("ResultT")


def run_in_sandbox(fn: Callable[[], ResultT]) -> ResultT:
    return fn()
