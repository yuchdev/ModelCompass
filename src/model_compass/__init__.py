"""Model Compass — request-aware LLM model analytics, comparison, and selection."""

from importlib.metadata import PackageNotFoundError, version

from model_compass.exceptions import (
    ConfigurationError,
    DependencyError,
    ModelCompassError,
)

try:
    __version__: str = version("model-compass")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"

from model_compass.application import analytics

__all__ = [
    "ConfigurationError",
    "DependencyError",
    "ModelCompassError",
    "__version__",
    "analytics",
]
