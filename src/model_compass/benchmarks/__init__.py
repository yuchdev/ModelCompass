"""Reproducible, task-aware benchmarking: datasets, evaluators, runner, and aggregation."""

from model_compass.benchmarks.aggregation import (
    ConfidenceInterval,
    QualitySummary,
    ScoredCase,
    bootstrap_confidence_interval,
    summarize_quality,
)
from model_compass.benchmarks.dataset import (
    DATASET_SCHEMA_VERSION,
    KNOWN_EVALUATOR_IDS,
    BenchmarkCase,
    BenchmarkDataset,
    DatasetIdentity,
    dump_dataset_jsonl,
    load_dataset_jsonl,
)
from model_compass.benchmarks.evaluators import (
    DETERMINISTIC_EVALUATORS,
    ContainsTermsEvaluator,
    EvaluationContext,
    EvaluationResult,
    Evaluator,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    JsonValidityEvaluator,
    NormalizedExactMatchEvaluator,
    NumericToleranceEvaluator,
    RegexEvaluator,
    resolve_evaluator,
)
from model_compass.benchmarks.external_evidence import (
    KNOWN_SCALES,
    ExternalEvidenceRecord,
    import_external_evidence,
    load_external_evidence_jsonl,
    normalize_external_score,
)
from model_compass.benchmarks.judge import (
    DEFAULT_JUDGE_PROMPT_TEMPLATE,
    JudgeConfig,
    JudgeEvaluationError,
    LLMJudgeEvaluator,
)
from model_compass.benchmarks.offline import (
    OfflineBenchmarkReport,
    OfflineCaseEvaluation,
    evaluate_offline,
)
from model_compass.benchmarks.runner import (
    BenchmarkRunConfig,
    BenchmarkRunOutcome,
    RunnerBudget,
    run_benchmark,
)

__all__ = [
    "DATASET_SCHEMA_VERSION",
    "DEFAULT_JUDGE_PROMPT_TEMPLATE",
    "DETERMINISTIC_EVALUATORS",
    "KNOWN_EVALUATOR_IDS",
    "KNOWN_SCALES",
    "BenchmarkCase",
    "BenchmarkDataset",
    "BenchmarkRunConfig",
    "BenchmarkRunOutcome",
    "ConfidenceInterval",
    "ContainsTermsEvaluator",
    "DatasetIdentity",
    "EvaluationContext",
    "EvaluationResult",
    "Evaluator",
    "ExactMatchEvaluator",
    "ExternalEvidenceRecord",
    "JsonSchemaEvaluator",
    "JsonValidityEvaluator",
    "JudgeConfig",
    "JudgeEvaluationError",
    "LLMJudgeEvaluator",
    "NormalizedExactMatchEvaluator",
    "NumericToleranceEvaluator",
    "OfflineBenchmarkReport",
    "OfflineCaseEvaluation",
    "QualitySummary",
    "RegexEvaluator",
    "RunnerBudget",
    "ScoredCase",
    "bootstrap_confidence_interval",
    "dump_dataset_jsonl",
    "evaluate_offline",
    "import_external_evidence",
    "load_dataset_jsonl",
    "load_external_evidence_jsonl",
    "normalize_external_score",
    "resolve_evaluator",
    "run_benchmark",
    "summarize_quality",
]
