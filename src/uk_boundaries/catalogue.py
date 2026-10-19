"""Load the existing static catalogue and select geography datasets."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from .downloads import download_dataset, resolve_downloads
from .http import read_json
from .models import BoundaryError, Dataset, DownloadOption, DownloadResult, JsonObject

DEFAULT_CATALOGUE_URL = "https://hulsiejames.github.io/uk-boundaries/catalogue.json"


def _dataset(row: object) -> Dataset:
    """Validate the fields consumed by the API without constraining extra metadata."""
    if not isinstance(row, dict):
        raise BoundaryError("Catalogue items must be JSON objects")
    if any(
        not isinstance(row.get(key), str) or not row[key]
        for key in ("id", "title", "kind", "source")
    ):
        raise BoundaryError("Catalogue records need string IDs, titles, kinds and source URLs")
    for key in ("levels", "countries"):
        if not isinstance(row.get(key), list) or any(not isinstance(v, str) for v in row[key]):
            raise BoundaryError(f"Catalogue {key} must be an array of strings")
    if not isinstance(row.get("years"), list) or any(
        not isinstance(v, int) or isinstance(v, bool) for v in row["years"]
    ):
        raise BoundaryError("Catalogue years must be an array of reference years")
    if not isinstance(row.get("service") or "", str) or not isinstance(
        row.get("variant", "Unspecified"), str
    ):
        raise BoundaryError("Invalid service or boundary variant")
    return Dataset(
        id=row["id"],
        title=row["title"],
        levels=tuple(row["levels"]),
        countries=tuple(row["countries"]),
        years=tuple(row["years"]),
        kind=row["kind"],
        variant=row.get("variant", "Unspecified"),
        source=row["source"],
        service=row.get("service") or "",
        record=row,
    )


class Catalogue:
    """Select explicit catalogue records before downloading their publisher files.

    Parameters
    ----------
    data : mapping
        A static catalogue with an items array and its reporting-level taxonomy.
        Construction and searching perform no network requests.
    """

    def __init__(self, data: Mapping[str, object]) -> None:
        payload = copy.deepcopy(dict(data))
        items = payload.get("items")
        if not isinstance(items, list):
            raise BoundaryError("Expected a catalogue object containing an items array")
        self.checked = str(payload.get("checked", ""))
        self.levels = tuple(cast(list[JsonObject], payload.get("levels", [])))
        self._datasets: dict[str, Dataset] = {}
        self._search: dict[str, str] = {}
        labels = {level["id"]: level for level in self.levels}
        for row in items:
            dataset = _dataset(row)
            if dataset.id in self._datasets:
                raise BoundaryError(f"Duplicate catalogue ID: {dataset.id}")
            self._datasets[dataset.id] = dataset
            terms = [dataset.title, dataset.id, *dataset.countries, dataset.variant]
            for level_id in dataset.levels:
                level = labels.get(level_id, {})
                terms.extend([level_id, level.get("label", ""), *level.get("aliases", [])])
            for area in row.get("areas", []):
                terms.extend([area.get("name", ""), area.get("code", "")])
            self._search[dataset.id] = " ".join(terms).casefold()

    @classmethod
    def from_file(cls, path: str | Path) -> Catalogue:
        """Load a local catalogue snapshot without requiring an internet connection."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise BoundaryError(f"Could not read catalogue: {path}") from exc
        if not isinstance(data, dict):
            raise BoundaryError("Expected a catalogue JSON object")
        return cls(data)

    @classmethod
    def from_url(cls, url: str = DEFAULT_CATALOGUE_URL, *, timeout: float = 30) -> Catalogue:
        """Fetch a published snapshot; this does not rescan government catalogues."""
        return cls(read_json(url, timeout=timeout))

    def get(self, record_id: str) -> Dataset:
        """Return an exact catalogue ID, raising KeyError when it is absent."""
        return copy.deepcopy(self._datasets[record_id])

    def search(
        self,
        query: str = "",
        *,
        level: str | None = None,
        country: str | None = None,
        year: int | None = None,
        kind: str | None = "boundary",
        variant: str | None = None,
    ) -> list[Dataset]:
        """Find records using reporting IDs, country coverage and reference years.

        Parameters
        ----------
        query : str
            Whole-word title, alias or audited authority-name search.
        level : str or None
            Reporting-level ID from catalogue.levels, such as lad or msoa.
        country : str or None
            A constituent country; UK-wide files also match each covered country.
        year : int or None
            A labelled reference year, including any year of a mixed-year lookup.
        kind : str or None
            Product type, defaulting to boundary. None includes every product.
        variant : str or None
            Publisher detail code, such as BFC or BFE.

        Returns
        -------
        list of Dataset
            Matching records in catalogue order. Selection never downloads files
            or silently picks one of several file vintages/variants.
        """
        if level is not None and level not in {row["id"] for row in self.levels}:
            raise ValueError(f"Unknown reporting-level ID: {level}")
        tokens = [
            re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)") for t in query.casefold().split()
        ]
        return [
            copy.deepcopy(dataset)
            for dataset in self._datasets.values()
            if (level is None or level in dataset.levels)
            and (
                country is None
                or country.casefold() in {c.casefold() for c in dataset.countries}
            )
            and (year is None or year in dataset.years)
            and (kind is None or kind == dataset.kind)
            and (variant is None or variant.casefold() == dataset.variant.casefold())
            and all(token.search(self._search[dataset.id]) for token in tokens)
        ]

    def resolve(
        self,
        record_id: str,
        *,
        layer_id: int | None = None,
        timeout: float = 30,
    ) -> list[DownloadOption]:
        """Resolve publisher file options, checking live ArcGIS metadata when needed."""
        return resolve_downloads(self.get(record_id), layer_id=layer_id, timeout=timeout)

    def download(
        self,
        record_id: str,
        output_dir: str | Path,
        *,
        format_preference: Sequence[str] = ("gpkg", "shapefile"),
        layer_id: int | None = None,
        overwrite: bool = False,
        timeout: float = 60,
        max_wait: float = 300,
        max_bytes: int = 2_000_000_000,
    ) -> DownloadResult:
        """Save a selected dataset, preferring publisher GeoPackage over shapefile.

        Parameters
        ----------
        record_id : str
            Exact catalogue ID selected using search or get.
        output_dir : str or Path
            Parent directory for an atomic, separately named dataset download.
        format_preference : sequence of str
            Ordered formats to try; supported values are gpkg and shapefile.
        layer_id : int or None
            Required when a service has multiple leaf layers. Never defaults to 0.
        overwrite : bool
            Replace an existing dataset directory only after validation succeeds.
        timeout : float
            Per-request socket timeout in seconds.
        max_wait : float
            Maximum preparation/polling time for a publisher export, in seconds.
        max_bytes : int
            Limit for both the transfer and total uncompressed archive contents.

        Returns
        -------
        DownloadResult
            Saved paths, actual format and a provenance manifest. No conversion
            or spatial translation is performed.
        """
        return download_dataset(
            self.get(record_id),
            output_dir,
            format_preference=format_preference,
            layer_id=layer_id,
            overwrite=overwrite,
            timeout=timeout,
            max_wait=max_wait,
            max_bytes=max_bytes,
            catalogue_checked=self.checked,
        )
