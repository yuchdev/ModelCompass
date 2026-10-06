"""Model Compass — request-aware LLM model analytics, comparison, and selection."""

from model_compass._version import __version__
from model_compass.application import analytics
from model_compass.domain import RequestProfile
from model_compass.exceptions import (
    BenchmarkError,
    ConfigurationError,
    DependencyError,
    ModelCompassError,
    NoEligibleModelError,
    PricingError,
    SelectionError,
    StorageError,
)
from model_compass.execution import ExecutionError
from model_compass.metrics import Observation
from model_compass.selection import (
    BenchmarkQualityProvider,
    InMemoryQualityProvider,
    MetricEvidence,
    ObjectiveDirection,
    ParetoObjective,
    ParetoResult,
    QualityProvider,
    SelectionDataPolicy,
    SelectionPolicy,
    estimate_request_cost,
    pareto_analysis,
    pareto_frontier,
    select_model,
    wilson_lower_bound,
)

__all__ = [
    "BenchmarkError",
    "BenchmarkQualityProvider",
    "ConfigurationError",
    "DependencyError",
    "ExecutionError",
    "InMemoryQualityProvider",
    "MetricEvidence",
    "ModelCompassError",
    "NoEligibleModelError",
    "ObjectiveDirection",
    "Observation",
    "ParetoObjective",
    "ParetoResult",
    "PricingError",
    "QualityProvider",
    "RequestProfile",
    "SelectionDataPolicy",
    "SelectionError",
    "SelectionPolicy",
    "StorageError",
    "__version__",
    "analytics",
    "estimate_request_cost",
    "pareto_analysis",
    "pareto_frontier",
    "select_model",
    "wilson_lower_bound",
]
