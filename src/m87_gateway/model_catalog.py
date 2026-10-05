"""Bounded, process-local snapshots from explicit operator model discovery."""

import time


class ModelCatalog:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._models: dict[str, tuple[str, float, tuple[str, ...]]] = {}

    def replace(self, provider: str, endpoint: str, models: list[str]) -> None:
        self._models[provider] = (endpoint, self._clock() + 900, tuple(sorted(set(models))[:2048]))

    def models(self, provider: str, endpoint: str) -> tuple[str, ...]:
        entry = self._models.get(provider)
        if not entry or entry[0] != endpoint or entry[1] <= self._clock():
            return ()
        return entry[2]

    def clear(self) -> None:
        self._models.clear()
