"""Catalog adapters and service facade."""

from model_compass.catalogs.exceptions import (
    CatalogCacheError,
    CatalogError,
    CatalogFetchError,
    CatalogParseError,
)
from model_compass.catalogs.litellm import LiteLLMCatalogAdapter
from model_compass.catalogs.merge import merge_catalog_snapshots
from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter
from model_compass.catalogs.protocols import CatalogProvider
from model_compass.catalogs.service import CatalogService

__all__ = [
    "CatalogCacheError",
    "CatalogError",
    "CatalogFetchError",
    "CatalogParseError",
    "CatalogProvider",
    "CatalogService",
    "LiteLLMCatalogAdapter",
    "OpenRouterCatalogAdapter",
    "merge_catalog_snapshots",
]
