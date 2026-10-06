"""Where finished executions are recorded as observations."""

from __future__ import annotations

from typing import Protocol

from model_compass.domain import Observation


class ObservationSink(Protocol):
    """Anything that can record a finished observation and return it as stored."""

    def record_observation(self, observation: Observation, *, deduplicate: bool = False) -> Observation:
        """Record one observation and return its stored representation."""
        ...  # pragma: no branch


class NullObservationSink:
    """Discards observations; use to execute without persistence."""

    def record_observation(self, observation: Observation, *, deduplicate: bool = False) -> Observation:
        """Return the observation unchanged without storing it."""
        del deduplicate
        return observation
