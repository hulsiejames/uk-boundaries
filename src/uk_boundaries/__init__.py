"""Find UK geography files and download publisher GeoPackages or shapefiles."""

from .catalogue import DEFAULT_CATALOGUE_URL, Catalogue
from .downloads import download_dataset, resolve_downloads
from .models import (
    AmbiguousLayerError,
    BoundaryError,
    Dataset,
    DownloadOption,
    DownloadResult,
    DownloadUnavailableError,
    InvalidDownloadError,
)

__all__ = [
    "DEFAULT_CATALOGUE_URL",
    "AmbiguousLayerError",
    "BoundaryError",
    "Catalogue",
    "Dataset",
    "DownloadOption",
    "DownloadResult",
    "DownloadUnavailableError",
    "InvalidDownloadError",
    "download_dataset",
    "resolve_downloads",
]
