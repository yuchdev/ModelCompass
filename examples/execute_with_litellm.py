from __future__ import annotations

import asyncio
import json
import os

from model_compass.execution import ExecutionRequest, LiteLLMBackend


def main() -> int:
    model_id = os.environ.get("MODEL_COMPASS_EXAMPLE_MODEL_ID", "openai/gpt-4o-mini")
    request = ExecutionRequest.from_prompt(model_id, "qa", "What is 2 + 2?", parameters={"max_tokens": 16})
    if os.environ.get("MODEL_COMPASS_EXAMPLE_RUN_LITELLM") != "1":
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "model_id": request.model_id,
                    "note": "Set MODEL_COMPASS_EXAMPLE_RUN_LITELLM=1 and provide provider credentials to make a live LiteLLM call.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = asyncio.run(LiteLLMBackend().execute(request))
    print(
        json.dumps(
            {"mode": "live", "model_id": result.model_id, "output_text": result.output_text}, indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
