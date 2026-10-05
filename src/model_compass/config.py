"""Platform-correct paths and configuration defaults.

No directory is created merely by importing this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

_APP_NAME = "model-compass"
_APP_AUTHOR = "model-compass"


@dataclass(frozen=True)
class AppPaths:
    """Resolved platform-correct application paths."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path


def default_paths() -> AppPaths:
    """Return default platform paths without creating any directories."""
    return AppPaths(
        config_dir=Path(user_config_dir(_APP_NAME, _APP_AUTHOR)),
        data_dir=Path(user_data_dir(_APP_NAME, _APP_AUTHOR)),
        cache_dir=Path(user_cache_dir(_APP_NAME, _APP_AUTHOR)),
    )
