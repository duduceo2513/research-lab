"""Generic retry/backoff and run-level budget enforcement.

Retrying is for transient failures of a *single* call (one provider, one fetch); it is not a
substitute for the orchestrator's own fault tolerance, which keeps the whole run going even when a
provider never recovers (see ``research_lab/README.md`` -> Fault tolerance).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from research_lab.exceptions import BudgetExceeded, RunCancelled

logger = logging.getLogger('research_lab')
T = TypeVar('T')


def retry_with_backoff(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 1.0,
                       max_delay: float = 10.0, exceptions: tuple[type[Exception], ...] = (Exception,)) -> T:
    """Calls ``fn()``, retrying on ``exceptions`` with exponential backoff. Re-raises the last
    exception once ``attempts`` is exhausted."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except exceptions as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.info('Retry %d/%d after %s (%.1fs backoff)', attempt + 1, attempts, exc, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


@dataclass
class Budget:
    """Tracks the run-wide limits the orchestrator enforces between every agent step."""

    max_steps: int
    max_runtime_seconds: float
    started_at: float
    steps_taken: int = 0

    @classmethod
    def start(cls, *, max_steps: int, max_runtime_seconds: float) -> 'Budget':
        return cls(max_steps=max_steps, max_runtime_seconds=max_runtime_seconds, started_at=time.monotonic())

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def check(self, *, cancel_requested: bool) -> None:
        """Raises ``RunCancelled``/``BudgetExceeded`` when the run must stop now."""
        if cancel_requested:
            raise RunCancelled('The user requested cancellation.')
        if self.steps_taken >= self.max_steps:
            raise BudgetExceeded(f'Exceeded the maximum of {self.max_steps} workflow steps.')
        if self.elapsed_seconds >= self.max_runtime_seconds:
            raise BudgetExceeded(f'Exceeded the maximum runtime of {self.max_runtime_seconds:.0f}s.')

    def step(self) -> None:
        self.steps_taken += 1
