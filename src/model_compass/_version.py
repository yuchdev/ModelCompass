"""Standalone package version resolution, kept free of any model_compass imports to avoid import cycles."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("model-compass")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"
