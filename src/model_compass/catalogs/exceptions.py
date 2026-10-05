"""Catalog-specific exceptions."""

from model_compass.exceptions import ModelCompassError


class CatalogError(ModelCompassError):
    """Base catalog error."""


class CatalogCacheError(CatalogError):
    """Raised when cache cannot be read for offline operations."""


class CatalogFetchError(CatalogError):
    """Raised when a provider catalog cannot be fetched."""


class CatalogParseError(CatalogError):
    """Raised when catalog payload cannot be parsed."""
