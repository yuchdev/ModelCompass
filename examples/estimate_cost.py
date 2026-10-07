from __future__ import annotations

import json

from _demo_common import demo_profiles, demo_request

from model_compass.metrics import FallbackTokenEstimator, estimate_cost


def main() -> int:
    profile, _ = demo_profiles()
    request = demo_request()
    token_estimate = FallbackTokenEstimator().estimate(
        model=profile.identity.canonical_id,
        explicit_input_tokens=request.explicit_input_tokens,
        expected_output_tokens=request.expected_output_tokens,
    )
    cost = estimate_cost(profile, token_estimate)
    payload = {
        "complete": cost.complete,
        "assumptions": list(cost.assumptions),
        "total": str(cost.total),
        "pricing_source": cost.pricing_source,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
