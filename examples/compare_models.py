from __future__ import annotations

import json

from _demo_common import demo_profiles, demo_request

from model_compass.metrics import FallbackTokenEstimator
from model_compass.selection import compare_models


def main() -> int:
    profiles = list(demo_profiles())
    report = compare_models(profiles, demo_request(), FallbackTokenEstimator())
    payload = {
        "selected_policy": report.selected_policy.value if report.selected_policy else None,
        "candidates": [
            {
                "model_id": candidate.model.identity.canonical_id,
                "eligible": candidate.eligibility.eligible,
                "cost": str(candidate.cost.total),
            }
            for candidate in report.candidates
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
