"""Public exception hierarchy for model_compass."""


class ModelCompassError(Exception):
    """Base exception for all model_compass errors."""


class ConfigurationError(ModelCompassError):
    """Raised when configuration is missing or invalid."""


class DependencyError(ModelCompassError):
    """Raised when a required optional dependency is unavailable."""
