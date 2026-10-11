"""Capture publisher metadata only: no features, geometry queries or file exports."""

from __future__ import annotations

import concurrent.futures
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from metadata_types import JsonObject


def write_metadata(metadata: JsonObject, path: str | Path) -> None:
    """Write the lazy schema cache as UTF-8 JSON with one record per line."""
    Path(path).write_text(
        '{"schemaVersion":1,"checked":'
        + json.dumps(metadata["checked"])
        + ',"records":{\n'
        + ",\n".join(
            json.dumps(k) + ":" + json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            for k, v in sorted(metadata["records"].items())
        )
        + "\n}}\n",
        encoding="utf-8",
        newline="\n",
    )


def timestamp(value: object) -> str | None:
    """Retain precision and explicit time zones; never invent a missing date."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return (
            datetime.fromtimestamp(value / 1000, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, str) and value.strip():
        value = value.strip()
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value  # Publisher ISO dates may deliberately have no time zone.
        except ValueError:
            pass
    return None


def date_value(value: object, basis: str, source: str) -> JsonObject | None:
    """Pair a valid publisher timestamp with its meaning and source URL."""
    stamp = timestamp(value)
    return dict(value=stamp, basis=basis, source=source) if stamp else None


def read_json(url: str) -> JsonObject:
    """Read a metadata endpoint and raise on explicit ArcGIS error responses."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "UK-Boundary-Atlas metadata index"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    return cast(JsonObject, data)


def normalize_layer(layer: JsonObject, url: str, hub: JsonObject | None = None) -> JsonObject:
    """Describe a layer using its schema and optional publisher Hub metadata.

    Parameters
    ----------
    layer : dict
        ArcGIS layer definition containing its actual layer ID and field schema.
    url : str
        Layer definition URL, used as the provenance of service metadata.
    hub : dict or None
        Matching Hub dataset attributes, including publisher date overrides.

    Returns
    -------
    dict
        Layer fields, CRS, availability, count and separately sourced dates.
        Export capabilities alone do not establish download availability.
    """
    hub = hub or {}
    metadata = (hub.get("metadata") or {}).get("metadata") or {}
    citation = ((metadata.get("dataIdInfo") or {}).get("idCitation") or {}).get("date") or {}
    if not isinstance(citation, dict):
        citation = {}
    hub_url = "https://hub.arcgis.com/api/v3/datasets/" + hub["id"] if hub.get("id") else url
    publication = date_value(
        citation.get("pubDate"), "Publisher metadata: published date", hub_url
    )
    publication = publication or date_value(
        citation.get("createDate"), "Publisher metadata: created date", hub_url
    )
    edit = layer.get("editingInfo") or {}
    updated = date_value(
        citation.get("reviseDate"), "Publisher metadata: revision date", hub_url
    )
    updated = updated or date_value(
        edit.get("dataLastEditDate"), "Service data last edited", url
    )
    # Hub's item-modified fallback is an information update, not evidence of a data edit.
    if (
        not updated
        and hub.get("modifiedProvenance")
        and "dataLastEditDate" in hub["modifiedProvenance"]
    ):
        updated = date_value(
            hub.get("modified"), "Hub data date: " + hub["modifiedProvenance"], hub_url
        )
    layer_fields = cast(list[JsonObject], layer.get("fields", hub.get("fields", [])))
    fields = [
        {k: f[k] for k in ("name", "alias", "type", "length", "nullable") if k in f}
        for f in layer_fields
        if f.get("name")
    ]
    result = dict(
        id=layer["id"],
        name=layer.get("name", str(layer["id"])),
        source=url,
        geometryType=layer.get("geometryType"),
        spatialReference=layer.get("spatialReference")
        or (layer.get("extent") or {}).get("spatialReference"),
        fields=fields,
        downloadable=hub.get("downloadable")
        if isinstance(hub.get("downloadable"), bool)
        else None,
        downloadSource="https://hub.arcgis.com/api/v3/datasets/" + hub["id"]
        if hub.get("id")
        else None,
        downloadPage="https://geoportal.statistics.gov.uk/datasets/" + hub["id"] + "/about"
        if hub.get("orgId") == "ESMARspQHYMw9BZ9" and hub.get("id")
        else None,
        serviceExportFormats=[
            x.strip() for x in layer.get("supportedExportFormats", "").split(",") if x.strip()
        ],
        recordCount=hub.get("recordCount"),
        publication=publication,
        dataUpdated=updated,
    )
    return result


def capture_service(row: JsonObject) -> JsonObject | None:
    """Capture definitions for real layer IDs without querying features.

    Parameters
    ----------
    row : dict
        Catalogue record with a public ArcGIS FeatureServer or MapServer URL.

    Returns
    -------
    dict or None
        Captured definitions and per-layer errors, or None for an unsupported
        service URL. A failed layer never discards other successful layers.
    """
    service = row["service"].rstrip("/")
    match = re.fullmatch(
        r"(https://[^?#]+/(?:FeatureServer|MapServer))(?:/(\d+))?", service, re.I
    )
    if not match:
        return None
    checked = datetime.now(timezone.utc).date().isoformat()
    result: JsonObject = dict(service=row["service"], checked=checked, layers=[], errors=[])
    try:
        root = read_json(match[1] + "?f=json")
        summaries = root.get("layers", []) + root.get("tables", [])
        if match[2] is not None:
            summaries = [dict(id=int(match[2]))]
        item_id = row["id"][4:] if row["id"].startswith("ons:") else root.get("serviceItemId")
        for summary in summaries:
            if summary.get("subLayerIds"):
                continue
            url = match[1] + "/" + str(summary["id"])
            try:
                layer = read_json(url + "?f=json")
                hub = {}
                if item_id:
                    try:
                        response = read_json(
                            "https://hub.arcgis.com/api/v3/datasets/"
                            + item_id
                            + "_"
                            + str(summary["id"])
                        )
                        hub = response["data"]["attributes"]
                    # Keep the layer schema when an optional publisher endpoint fails.
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        result["errors"].append(
                            "Hub layer " + str(summary["id"]) + ": " + str(exc)
                        )
                result["layers"].append(normalize_layer(layer, url, hub))
            # Capture failures per layer so other layer definitions remain usable.
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result["errors"].append("Layer " + str(summary["id"]) + ": " + str(exc))
    # Preserve a reportable failure rather than aborting the complete catalogue scan.
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result["errors"].append("Service: " + str(exc))
    if not result["layers"] and not result["errors"]:
        result["errors"].append("Service returned no readable layer or table metadata")
    result["status"] = (
        "partial"
        if result["errors"] and result["layers"]
        else "unavailable"
        if result["errors"]
        else "captured"
    )
    return result


def refresh_metadata(rows: list[JsonObject], previous: JsonObject | None = None) -> JsonObject:
    """Refresh active service definitions while retaining complete prior captures.

    Parameters
    ----------
    rows : list of dict
        Current catalogue records. Unsupported service types are skipped.
    previous : dict or None
        Last schema cache, with original successful check dates.

    Returns
    -------
    dict
        Active metadata cache. Failed or partial refreshes keep eligible previous
        captures and record the latest failure separately; changed service URLs
        invalidate the old schema association.
    """
    previous = previous or {"records": {}}
    active = {r["id"] for r in rows}
    records = {key: value for key, value in previous["records"].items() if key in active}
    eligible = [
        r
        for r in rows
        if re.fullmatch(
            r"https://[^?#]+/(?:FeatureServer|MapServer)(?:/\d+)?/?",
            r.get("service", ""),
            re.I,
        )
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for index, (row, entry) in enumerate(
            zip(eligible, pool.map(capture_service, eligible), strict=False), 1
        ):
            assert entry is not None  # Eligible URLs have already matched the capture pattern.
            old = records.get(row["id"])
            if (
                entry["status"] in ("unavailable", "partial")
                and old
                and old["service"] == row["service"]
                and old.get("layers")
                and (entry["status"] == "unavailable" or old["status"] == "captured")
            ):
                entry = dict(
                    old, lastAttempt=entry["checked"], lastAttemptErrors=entry["errors"]
                )
            records[row["id"]] = entry
            if index % 100 == 0 or index == len(eligible):
                print(f"Captured publisher metadata: {index}/{len(eligible)}", flush=True)
    return dict(
        schemaVersion=1, checked=datetime.now(timezone.utc).date().isoformat(), records=records
    )


def apply_metadata(row: JsonObject, entry: JsonObject | None = None) -> JsonObject:
    """Enrich a record in place with dates and a pointer to its lazy field schema.

    Parameters
    ----------
    row : dict
        Catalogue record to enrich, keeping its geography vintage unchanged.
    entry : dict or None
        Capture for the same service URL. Mismatched captures are not reused.

    Returns
    -------
    dict
        The same record, with sourced dates and explicit download status.
        Mixed layer dates remain per layer instead of becoming dataset dates.
    """
    dates: JsonObject = dict(
        uploaded=date_value(
            row.get("uploaded") or row.get("published"),
            "Source item created / uploaded",
            row.get("itemUrl") or row["source"],
        ),
        infoUpdated=date_value(
            row.get("infoUpdated") or row.get("modified"),
            "Source item metadata modified",
            row.get("itemUrl") or row["source"],
        ),
        published=None,
        dataUpdated=None,
    )
    status = "direct" if row["downloads"] else "unknown"
    download: JsonObject = dict(
        status=status,
        basis="Indexed direct file link"
        if row["downloads"]
        else "Download availability not confirmed",
        source=row["source"],
    )
    if entry and entry["service"] == row.get("service"):
        layers = entry.get("layers", [])
        available = [layer for layer in layers if layer.get("downloadable") is True]
        if not row["downloads"] and available:
            download = dict(
                status="publisher",
                basis="Publisher Hub metadata reports downloadable layers",
                source=available[0]["downloadSource"],
                pages=[
                    layer["downloadPage"] for layer in available if layer.get("downloadPage")
                ],
            )
        elif (
            not row["downloads"]
            and layers
            and entry["status"] == "captured"
            and all(layer.get("downloadable") is False for layer in layers)
        ):
            download = dict(
                status="not-offered",
                basis="Publisher Hub metadata reports downloads disabled",
                source=layers[0]["downloadSource"],
            )
        for key, layer_key in [("published", "publication"), ("dataUpdated", "dataUpdated")]:
            known = [layer[layer_key] for layer in layers if layer.get(layer_key)]
            # Mixed/partial dates stay per layer rather than becoming a false dataset date.
            if known and len(known) == len(layers) and len({d["value"] for d in known}) == 1:
                dates[key] = known[0]
        row["attributes"] = dict(
            key=row["id"],
            status=entry["status"],
            checked=entry["checked"],
            layers=len(layers),
            fields=sum(len(layer["fields"]) for layer in layers),
        )
    download["checked"] = (
        entry["checked"]
        if entry and entry["service"] == row.get("service") and status != "direct"
        else row.get("checked")
    )
    row["downloadAvailability"] = download
    row["dates"] = dates
    return row
