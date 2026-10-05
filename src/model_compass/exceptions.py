"""Public exception hierarchy for model_compass."""


class ModelCompassError(Exception):
    """Base exception for all model_compass errors."""


class ConfigurationError(ModelCompassError):
    """Raised when configuration is missing or invalid."""


class DependencyError(ModelCompassError):
    """Raised when a required optional dependency is unavailable."""


class PricingError(ModelCompassError, ValueError):
    """Raised when a pricing value cannot be parsed or calculated."""


class SelectionError(ModelCompassError, ValueError):
    """Raised when a selection policy or Pareto request is invalid."""


class BenchmarkError(ModelCompassError, ValueError):
    """Raised when a benchmark dataset or evaluation request is invalid."""


class StorageError(ModelCompassError):
    """Raised when local analytics storage cannot be read or written."""
