# 02 - Health endpoint

**Parent story:** [README.md](README.md)
**Status:** ⬜ Not started
**Depends on:** [01-config-model.md](01-config-model.md)

## Requirements

- Add a `GET /health` route that returns `{"status": "ok", "service": <service_name>}`
  with a `200` status code.
- `service_name` comes from `HealthConfig` (task 01) - no hardcoded string.

## Files

- `src/model_compass/api/health.py` - new route handler.
- Wire the route into the app's existing router setup.
