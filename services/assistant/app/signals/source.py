from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from .models import Signal


class SignalSource(ABC):
    @abstractmethod
    def fetch(self) -> List[Signal]:
        """Return a list of signals. Read-only by contract."""
        raise NotImplementedError


class NullSignalSource(SignalSource):
    def fetch(self) -> List[Signal]:
        return []
