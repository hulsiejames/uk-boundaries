"""Resolve public publisher exports and atomically save validated spatial files."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import zipfile
from collections.abc import Sequence
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .http import Response, open_url, public_url, read_json, validate_url
from .models import (
    AmbiguousLayerError,
    BoundaryError,
    Dataset,
    DownloadOption,
    DownloadResult,
    DownloadUnavailableError,
    InvalidDownloadError,
    JsonObject,
)


@dataclass(frozen=True)
class _Settings:
    """Keep transfer and output limits consistent across format fallbacks."""

    timeout: float
    max_wait: float
    max_bytes: int
    overwrite: bool
    catalogue_checked: str


def _format(value: str) -> str | None:
    """Normalise the two supported spatial file formats."""
    return {
        "gpkg": "gpkg",
        "geopackage": "gpkg",
        "shp": "shapefile",
        "shapefile": "shapefile",
    }.get(value.strip().casefold())


def _hub_options(
    dataset: Dataset, layer_id: int | None, timeout: float
) -> list[DownloadOption]:
    """Use actual layer IDs and publisher download flags to resolve Hub exports."""
    match = re.fullmatch(
        r"(https://[^?#]+/(?:FeatureServer|MapServer))(?:/(\d+))?/?", dataset.service, re.I
    )
    if not match:
        return []
    root = read_json(match[1] + "?f=json", timeout=timeout)
    summaries = root.get("layers", []) + root.get("tables", [])
    ids = [int(row["id"]) for row in summaries if not row.get("subLayerIds")]
    explicit = int(match[2]) if match[2] is not None else None
    if explicit is not None:
        if layer_id is not None and layer_id != explicit:
            raise ValueError("layer_id conflicts with the selected record's service layer")
        selected = explicit
    elif layer_id is not None:
        selected = layer_id
    elif len(ids) == 1:
        selected = ids[0]
    else:
        raise AmbiguousLayerError(f"Select layer_id from the publisher's layer IDs: {ids}")
    if selected not in ids:
        raise ValueError(f"layer_id {selected} is absent from this service: {ids}")
    item_id = (
        dataset.id[4:] if dataset.id.startswith("ons:") else root.get("serviceItemId", "")
    )
    if not re.fullmatch(r"[a-fA-F0-9]{32}", str(item_id)):
        raise DownloadUnavailableError(
            "No public ArcGIS item ID could be resolved for this service"
        )
    hub = (
        read_json(
            f"https://hub.arcgis.com/api/v3/datasets/{item_id}_{selected}", timeout=timeout
        )
        .get("data", {})
        .get("attributes", {})
    )
    if hub.get("downloadable") is not True:
        raise DownloadUnavailableError(
            "Publisher Hub metadata does not confirm public downloads"
        )
    layer = read_json(f"{match[1]}/{selected}?f=json", timeout=timeout)
    if not layer.get("geometryType"):
        raise DownloadUnavailableError(
            "This service layer is a table without spatial geometry"
        )
    supported = {
        s.strip().casefold() for s in layer.get("supportedExportFormats", "").split(",")
    }
    formats = ["gpkg", "shapefile"] if "geopackage" in supported else ["shapefile"]
    return [
        DownloadOption(
            fmt,
            f"https://hub.arcgis.com/api/download/v1/items/{item_id}/"
            f"{'geoPackage' if fmt == 'gpkg' else 'shapefile'}?layers={selected}",
            selected,
        )
        for fmt in formats
    ]


def resolve_downloads(
    dataset: Dataset,
    *,
    layer_id: int | None = None,
    timeout: float = 30,
) -> list[DownloadOption]:
    """Return public direct-file and live Hub options in GeoPackage-first order.

    Parameters
    ----------
    dataset : Dataset
        Exact catalogue record selected by the caller.
    layer_id : int or None
        Explicit ArcGIS layer selection when required; direct bundles are not filtered.
    timeout : float
        Per-metadata-request timeout in seconds.

    Returns
    -------
    list of DownloadOption
        Publisher URLs and actual layer IDs. Unsupported WFS/page-only routes raise
        DownloadUnavailableError; a service capability alone does not confirm a download.
    """
    if layer_id is not None and (
        not isinstance(layer_id, int) or isinstance(layer_id, bool) or layer_id < 0
    ):
        raise ValueError("layer_id must be a non-negative integer")
    options = [
        DownloadOption(fmt, validate_url(link["url"]))
        for link in dataset.record.get("downloads", [])
        if (fmt := _format(link.get("format", ""))) and layer_id is None
    ]
    try:
        options.extend(_hub_options(dataset, layer_id, timeout))
    except AmbiguousLayerError:
        if not options:
            raise
    except BoundaryError as exc:
        if not options:
            raise DownloadUnavailableError(str(exc)) from exc
    if not options:
        raise DownloadUnavailableError(
            f"No public GeoPackage/shapefile route; inspect {dataset.source}"
        )
    return sorted(dict.fromkeys(options), key=lambda option: option.format != "gpkg")


def _poll_url(response: Response, first: bytes, url: str, deadline: float) -> str:
    """Interpret one asynchronous export response within the preparation deadline."""
    raw = first + response.read(65536)
    if len(raw) > 65536:
        raise InvalidDownloadError("Publisher returned an oversized JSON download response")
    try:
        data = json.loads(raw) if raw else {}
    except ValueError as exc:
        raise InvalidDownloadError("Publisher returned invalid export-status JSON") from exc
    if not isinstance(data, dict) or "error" in data:
        raise DownloadUnavailableError("Publisher returned an export error")
    state = str(data.get("status", "")).casefold()
    if state in {"failed", "error", "cancelled"}:
        raise DownloadUnavailableError("Publisher export failed")
    destination = data.get("downloadUrl") or data.get("resultUrl")
    if destination:
        next_url = validate_url(urllib.parse.urljoin(url, destination))
        if next_url == url:
            raise InvalidDownloadError("Publisher export refers back to its status response")
        return next_url
    if response.status != 202 and state not in {"pending", "processing", "queued", "running"}:
        raise DownloadUnavailableError("Publisher returned JSON instead of a spatial file")
    location = response.headers.get("Location")
    next_url = validate_url(urllib.parse.urljoin(url, location)) if location else url
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DownloadUnavailableError("Timed out waiting for the publisher export")
    time.sleep(min(2, remaining))
    return next_url


def _transfer(
    option: DownloadOption,
    target: Path,
    timeout: float,
    max_wait: float,
    max_bytes: int,
) -> tuple[str, int, str]:
    """Stream a publisher export, polling bounded asynchronous responses when needed."""
    deadline = time.monotonic() + max_wait
    url = option.url
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DownloadUnavailableError("Timed out waiting for the publisher export")
        with open_url(url, timeout=min(timeout, remaining)) as response:
            first = response.read(512)
            is_json = "json" in response.headers.get("Content-Type", "").casefold()
            if response.status == 202 or is_json or first.lstrip().startswith((b"{", b"[")):
                url = _poll_url(response, first, url, deadline)
                continue
            length = response.headers.get("Content-Length")
            expected = int(length) if length and length.isdecimal() else None
            if expected is not None and expected > max_bytes:
                raise InvalidDownloadError("Publisher file exceeds max_bytes")
            digest = hashlib.sha256()
            count = 0
            with target.open("wb") as output:
                chunk = first
                while chunk:
                    count += len(chunk)
                    if count > max_bytes:
                        raise InvalidDownloadError("Publisher file exceeds max_bytes")
                    output.write(chunk)
                    digest.update(chunk)
                    chunk = response.read(1024 * 1024)
            if expected is not None and count != expected:
                raise InvalidDownloadError(
                    "Publisher response ended before Content-Length was received"
                )
            return digest.hexdigest(), count, public_url(response.geturl())


def _archive_files(payload: Path, directory: Path, max_bytes: int) -> None:
    """Validate every archive member before extracting inside the staging directory."""
    with zipfile.ZipFile(payload) as archive:
        members = archive.infolist()
        total = 0
        names: set[str] = set()
        for member in members:
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
                raise InvalidDownloadError(
                    "Archive contains a path outside the output directory"
                )
            if any(p.rstrip(" .") != p for p in path.parts):
                raise InvalidDownloadError(
                    "Archive contains ambiguous Windows path components"
                )
            if any(
                re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
                for p in path.parts
            ):
                raise InvalidDownloadError("Archive contains a reserved Windows device name")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise InvalidDownloadError("Archive contains a symbolic link")
            if name.casefold() in names or "\x00" in name:
                raise InvalidDownloadError(
                    "Archive contains duplicate or invalid member paths"
                )
            names.add(name.casefold())
            total += member.file_size
            if total > max_bytes:
                raise InvalidDownloadError("Uncompressed archive exceeds max_bytes")
        for member in members:
            destination = directory.joinpath(
                *PurePosixPath(member.filename.replace("\\", "/")).parts
            )
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)


def _spatial_files(
    payload: Path, directory: Path, fmt: str, max_bytes: int
) -> tuple[Path, ...]:
    """Validate actual GeoPackages or complete shapefile sets, retaining publisher bytes."""
    if zipfile.is_zipfile(payload):
        _archive_files(payload, directory, max_bytes)
    elif fmt == "gpkg":
        shutil.copyfile(payload, directory / "data.gpkg")
    else:
        raise InvalidDownloadError(
            "Expected a ZIP containing shapefile .shp/.shx/.dbf sidecars"
        )
    paths = tuple(
        sorted(
            p
            for p in directory.rglob("*")
            if p.is_file() and p.suffix.casefold() == (".gpkg" if fmt == "gpkg" else ".shp")
        )
    )
    if not paths:
        raise InvalidDownloadError(f"Publisher response contains no {fmt} files")
    for path in paths:
        if fmt == "gpkg":
            try:
                with closing(
                    sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                ) as database:
                    tables = {
                        row[0]
                        for row in database.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if (
                        not {"gpkg_contents", "gpkg_spatial_ref_sys", "gpkg_geometry_columns"}
                        <= tables
                    ):
                        raise InvalidDownloadError(
                            "SQLite file does not contain GeoPackage metadata"
                        )
            except sqlite3.DatabaseError as exc:
                raise InvalidDownloadError(
                    "Publisher response is not a GeoPackage database"
                ) from exc
        else:
            siblings = {p.name.casefold(): p for p in path.parent.iterdir() if p.is_file()}
            if any(
                (path.stem + extension).casefold() not in siblings
                for extension in (".shx", ".dbf")
            ):
                raise InvalidDownloadError("Shapefile is missing a .shx or .dbf sidecar")
            with path.open("rb") as source:
                if source.read(4) != b"\x00\x00\x27\x0a":
                    raise InvalidDownloadError(
                        "Publisher response has an invalid shapefile header"
                    )
    return paths


def _publish(content: Path, destination: Path, root: Path, overwrite: bool) -> None:
    """Replace a requested output atomically, restoring its previous version on failure."""
    if destination.parent != root or not destination.resolve().is_relative_to(root):
        raise InvalidDownloadError("Output destination escapes the requested directory")
    if destination.is_symlink():
        raise FileExistsError("Refusing to replace a symlink output destination")
    previous = root / f".{destination.name}.previous-{uuid4().hex}"
    if destination.exists():
        if not overwrite or not destination.is_dir():
            raise FileExistsError(destination)
        destination.rename(previous)
    try:
        content.rename(destination)
    except OSError:
        if previous.exists():
            previous.rename(destination)
        raise
    # A failed restoration leaves the old output outside temporary-directory cleanup.
    if previous.exists() and previous.resolve().is_relative_to(root):
        with suppress(OSError):
            shutil.rmtree(previous)


def _save_option(
    dataset: Dataset,
    option: DownloadOption,
    root: Path,
    settings: _Settings,
    failures: list[str],
) -> DownloadResult:
    """Stage one format and publish it only after spatial-file validation succeeds."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", dataset.id).strip("-")
    if not name:
        raise ValueError("Catalogue record ID cannot be used as an output name")
    layer = f"layer-{option.layer_id}-" if option.layer_id is not None else ""
    destination = root / f"{name}-{layer}{option.format}"
    if (destination.exists() or destination.is_symlink()) and not settings.overwrite:
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix=".uk-boundaries-", dir=root) as temporary:
        staging = Path(temporary)
        content = staging / "content"
        content.mkdir()
        payload = staging / "download.part"
        digest, size, final_url = _transfer(
            option, payload, settings.timeout, settings.max_wait, settings.max_bytes
        )
        paths = _spatial_files(payload, content, option.format, settings.max_bytes)
        relative = tuple(p.relative_to(content) for p in paths)
        manifest: JsonObject = dict(
            record_id=dataset.id,
            title=dataset.title,
            reference_years=dataset.years,
            publisher_source=public_url(dataset.source),
            catalogue_checked=settings.catalogue_checked,
            dataset_checked=dataset.record.get("checked"),
            layer_id=option.layer_id,
            format=option.format,
            requested_url=public_url(option.url),
            final_url=final_url,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            payload_sha256=digest,
            downloaded_bytes=size,
            data_files=[p.as_posix() for p in relative],
            failed_attempts=list(failures),
        )
        (content / "download-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _publish(content, destination, root, settings.overwrite)
    return DownloadResult(
        dataset.id,
        option.format,
        destination,
        tuple(destination / p for p in relative),
        destination / "download-manifest.json",
        public_url(option.url),
    )


def download_dataset(
    dataset: Dataset,
    output_dir: str | Path,
    *,
    format_preference: Sequence[str] = ("gpkg", "shapefile"),
    layer_id: int | None = None,
    overwrite: bool = False,
    timeout: float = 60,
    max_wait: float = 300,
    max_bytes: int = 2_000_000_000,
    catalogue_checked: str = "",
) -> DownloadResult:
    """Save publisher spatial data in a validated, atomic dataset directory.

    Parameters
    ----------
    dataset : Dataset
        Selected static catalogue record; its reference vintage is retained.
    output_dir : str or Path
        Parent directory for downloaded data and provenance.
    format_preference : sequence of str
        Ordered supported formats, normally gpkg followed by shapefile.
    layer_id : int or None
        Explicit service layer when several layers are available.
    overwrite : bool
        Allow replacing an existing dataset directory after validation.
    timeout : float
        Per-request timeout in seconds.
    max_wait : float
        Maximum wait for a queued export, in seconds.
    max_bytes : int
        Maximum transfer and uncompressed archive size in bytes.
    catalogue_checked : str
        Published catalogue check date retained in the manifest.

    Returns
    -------
    DownloadResult
        Spatial paths, actual format, public source link and provenance manifest.
        Existing successful outputs survive failed transfers or validation.
    """
    preferences = list(dict.fromkeys(_format(value) for value in format_preference))
    if not preferences or None in preferences:
        raise ValueError("format_preference must contain gpkg and/or shapefile")
    if max_wait <= 0 or max_bytes <= 0 or timeout <= 0:
        raise ValueError("timeout, max_wait and max_bytes must be positive")
    options = resolve_downloads(dataset, layer_id=layer_id, timeout=timeout)
    ordered = sorted(
        (o for o in options if o.format in preferences),
        key=lambda o: preferences.index(o.format),
    )
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    settings = _Settings(timeout, max_wait, max_bytes, overwrite, catalogue_checked)
    for option in ordered:
        try:
            return _save_option(dataset, option, root, settings, failures)
        except FileExistsError:
            raise
        except (
            BoundaryError,
            OSError,
            ValueError,
            zipfile.BadZipFile,
            urllib.error.URLError,
        ) as exc:
            failures.append(f"{option.format}: {type(exc).__name__}: {exc}")
    raise DownloadUnavailableError(
        "No requested format could be saved. " + "; ".join(failures)
    )
