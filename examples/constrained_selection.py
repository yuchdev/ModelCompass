from __future__ import annotations

import json
from decimal import Decimal

from _demo_common import demo_profiles, demo_request

from model_compass import SelectionPolicy, analytics
from model_compass.selection import InMemoryQualityProvider, MetricEvidence


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
    result = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST, quality_provider=provider)
    payload = {
        "selected": None if result.selected is None else result.selected.model_id,
        "rejections": result.rejection_counts,
        "selected_policy": result.policy.value,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
