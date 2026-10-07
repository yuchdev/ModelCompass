from __future__ import annotations

import json
from decimal import Decimal

from _demo_common import demo_profiles, demo_request

from model_compass import SelectionPolicy
from model_compass.selection import (
    InMemoryQualityProvider,
    MetricEvidence,
    ParetoObjective,
    pareto_frontier,
    select_model,
)


def main() -> int:
    profiles = list(demo_profiles())
    request = demo_request()
    provider = InMemoryQualityProvider(
        {
            "demo:small": MetricEvidence(
                value=Decimal("0.91"), source="benchmark", task="summarization", sample_count=12
            ),
            "demo:large": MetricEvidence(
                value=Decimal("0.97"), source="benchmark", task="summarization", sample_count=12
            ),
        }
    )
    result = select_model(profiles, request, policy=SelectionPolicy.BEST, quality_provider=provider)
    frontier = pareto_frontier(result.assessments, [ParetoObjective.QUALITY, ParetoObjective.COST])
    payload = {
        "frontier": [candidate.model_id for candidate in frontier],
        "selected": None if result.selected is None else result.selected.model_id,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
