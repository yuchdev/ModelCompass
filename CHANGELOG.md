# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Execution: backend-neutral `ExecutionBackend.execute`, `ExecutionRequest`, `UsageRecord`, `CostReconciliation`, failure taxonomy, streaming/TTFT, and `AnalyticsFacade.select_and_execute`
- Documentation: quickstart, configuration, offline-use, compare-models, select-model, reference API, and example scripts for core workflows
- Repository bootstrap: package skeleton, CLI skeleton, quality gates, CI
- CLI commands: `--help`, `version`, `doctor`
- Exception hierarchy: `ModelCompassError`, `ConfigurationError`, `DependencyError`
- Platform-correct paths via `platformdirs`
- Ruff, MyPy, pytest, coverage configuration
- Documentation skeleton
