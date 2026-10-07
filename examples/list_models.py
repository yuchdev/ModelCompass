from __future__ import annotations

import json

from _demo_common import demo_profiles


def main() -> int:
    profiles = demo_profiles()
    payload = {
        "models": [
            {
                "canonical_id": profile.identity.canonical_id,
                "provider": profile.identity.provider,
                "model_id": profile.identity.model_id,
                "input_modalities": list(profile.capabilities.input_modalities),
                "output_modalities": list(profile.capabilities.output_modalities),
            }
            for profile in profiles
        ]
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
