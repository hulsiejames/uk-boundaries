"""Public, typed catalogue and download results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]


class BoundaryError(Exception):
    """Report a catalogue, publisher-resolution or download failure."""


class DownloadUnavailableError(BoundaryError):
    """Report that no requested public file format could be downloaded."""


class AmbiguousLayerError(BoundaryError):
    """Require an explicit layer selection for a service with multiple layers."""


class InvalidDownloadError(BoundaryError):
    """Reject incomplete files, unexpected formats and unsafe archives."""


@dataclass(frozen=True)
class Dataset:
    """Describe a catalogue item; its reference years are separate from upload dates."""

    id: str
    title: str
    levels: tuple[str, ...]
    countries: tuple[str, ...]
    years: tuple[int, ...]
    kind: str
    variant: str
    source: str
    service: str
    record: JsonObject = field(repr=False, compare=False)


@dataclass(frozen=True)
class DownloadOption:
    """Describe a direct publisher file or a public Hub export route."""

    format: str
    url: str
    layer_id: int | None = None


@dataclass(frozen=True)
class DownloadResult:
    """Return saved spatial files and their source-provenance manifest."""

    record_id: str
    format: str
    directory: Path
    paths: tuple[Path, ...]
    manifest_path: Path
    source_url: str

    @property
    def path(self) -> Path:
        """Return the single spatial file; require paths for a multi-file bundle."""
        if len(self.paths) != 1:
            raise AmbiguousLayerError(
                "This bundle has multiple spatial files; use result.paths"
            )
        return self.paths[0]
