"""Rebuild a metadata-only UK catalogue. No polygons or inferred legal validity."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from catalogue_config import ALL, EW, GB, LEVELS, PROVIDERS
from dataset_metadata import apply_metadata, refresh_metadata, timestamp, write_metadata
from metadata_types import JsonObject

ROOT = Path(__file__).resolve().parent
YEAR = datetime.now(timezone.utc).year
ORG = "ESMARspQHYMw9BZ9"
TYPES = ["Feature Service", "Shapefile", "CSV Collection", "Microsoft Excel", "CSV", "GeoJson"]
DATE_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def get_json(url: str) -> JsonObject:
    """Read publisher JSON, raising on transport or explicit ArcGIS errors."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "UK-Boundary-Atlas metadata index"}
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    if "error" in data:
        raise RuntimeError(data["error"])
    return cast(JsonObject, data)


def fetch_ons() -> list[JsonObject]:
    """Fetch all supported ONS items and reject incomplete or duplicate pagination."""
    query = f"orgid:{ORG} AND (" + " OR ".join(f'type:"{t}"' for t in TYPES) + ")"
    items: list[JsonObject] = []
    start, total = 1, None
    while start != -1:
        params = dict(
            f="json", q=query, num=100, start=start, sortField="title", sortOrder="asc"
        )
        data = get_json(
            "https://www.arcgis.com/sharing/rest/search?" + urllib.parse.urlencode(params)
        )
        if total is None:
            total = data["total"]
        items.extend(data["results"])
        start = data["nextStart"]
        if len(items) % 500 == 0 or start == -1:
            print(f"Read {len(items)} of {total} ONS items", flush=True)
    if len(items) != total or len({x["id"] for x in items}) != len(items):
        raise RuntimeError("Incomplete or unstable ONS pagination; retry the refresh.")
    return items


def title_years(title: str) -> list[int]:
    """Read reference years from labelled titles, never upload timestamps."""
    return sorted({int(y) for y in DATE_RE.findall(title) if int(y) <= YEAR})


def scope(title: str) -> list[str]:
    """Return title-labelled countries, leaving unlabelled scope unknown."""
    patterns = [
        (r"\b(UK|United Kingdom)\b", ALL),
        (r"\b(GB|Great Britain)\b", GB),
        (r"\b(EW|England and Wales)\b", EW),
        (r"\b(EN|England)\b", ["England"]),
        (r"\b(WA|Wales)\b", ["Wales"]),
        (r"\b(SC|Scotland)\b", ["Scotland"]),
        (r"\b(NI|Northern Ireland)\b", ["Northern Ireland"]),
    ]
    for pattern, countries in patterns:
        if re.search(pattern, title, re.I):
            return countries.copy()
    return []  # Do not infer national scope from a bounding box or upload date.


def levels_for_title(title: str) -> list[str]:
    """Match reporting levels while excluding overlapping higher-level titles."""
    ids = [x["id"] for x in LEVELS if x["pattern"] and re.search(x["pattern"], title, re.I)]
    if "Sub Integrated Care Board" in title:
        ids = [x for x in ids if x != "icb"]
    if "Counties and Unitary Authorities" in title:
        ids = [x for x in ids if x != "county"]
    return ids or ["other"]


def product_kind(title: str) -> str | None:
    """Classify a labelled geography product or return None for unsupported items."""
    t = title.lower()
    if "user guide" in t or "guidance" in t:
        return "reference"
    if "code history database" in t or "register of geographic codes" in t:
        return "reference"
    if any(x in t for x in ["lookup", "look-up", "linkage", "matching file"]):
        return "lookup"
    if "boundaries" in t or re.search(r"\bboundary\b", t):
        return "reference" if "guidance" in t or "releases" in t else "boundary"
    if "centroid" in t:
        return "centroid"
    if any(x in t for x in ["names and codes", "name and code", "directory"]):
        return "reference"
    return None


def boundary_variant(title: str) -> str:
    """Preserve the publisher's boundary detail code without inferring resolution."""
    code = re.search(r"\b(BFE|BFC|BGE|BGC|BGG|BSC|BSE|BUC|BUE|BNC)\b", title, re.I)
    if code:
        return code.group(1).upper()
    for text, value in [
        ("full clipped", "BFC"),
        ("full extent", "BFE"),
        ("super generalised", "BSC"),
        ("generalised", "BGC"),
    ]:
        if text in title.lower():
            return value
    return "Unspecified"


def centroid_weight(title: str, kind: str) -> str:
    """Return a labelled centroid method without inferring weighting from geography."""
    if kind != "centroid":
        return ""
    t = title.lower().replace("-", " ")
    for pattern, weight in [
        ("employment weighted", "employment"),
        ("workplace weighted", "employment"),
        ("population weighted", "population"),
        ("address weighted", "address"),
        ("geometric", "geometric"),
    ]:
        if pattern in t:
            return weight
    return "not-specified"


def _date_prefix(value: object) -> str | None:
    """Retain the existing date-only item timestamp alongside precise metadata."""
    stamp = timestamp(value)
    return stamp[:10] if stamp else None


def normalize_ons(item: JsonObject) -> JsonObject | None:
    """Normalise an ONS item without changing its reference-vintage semantics.

    Parameters
    ----------
    item : dict
        Publisher item JSON, including its labelled title, type and timestamps.

    Returns
    -------
    dict or None
        Metadata for a supported geography product. Unsupported, pre-2001 and
        future-labelled items are omitted; mixed-year lookups retain every year.
    """
    title = item["title"].strip()
    kind = product_kind(title)
    if not kind:
        return None
    years = title_years(title)
    if years and min(years) < 2001:
        return None
    if re.search(r"\b20\d{2}\b", title) and not years:
        return None
    countries = scope(title)
    ids = levels_for_title(title)
    if countries == ["Scotland"] and "oa-ew" in ids:
        ids[ids.index("oa-ew")] = "oa-sc"
    if countries == ["Northern Ireland"] and "oa-ew" in ids:
        ids[ids.index("oa-ew")] = "oa-ni"
    ordered = list(dict.fromkeys(int(y) for y in DATE_RE.findall(title) if int(y) <= YEAR))
    # A mixed-vintage lookup has no single boundary year. All references are retained.
    year = ordered[0] if kind != "lookup" and ordered else None
    vintage = " / ".join(map(str, ordered)) if ordered else "Not labelled"
    date = re.search(r"\(([^)]*\b(?:19|20)\d{2}\b[^)]*)\)", title)
    if kind != "lookup" and date:
        vintage = date.group(1)
    method = (
        next(
            (
                n
                for n in ["Exact Fit", "Best Fit", "Population Weighted", "Area Weighted"]
                if n.lower() in title.lower()
            ),
            "Not specified",
        )
        if kind == "lookup"
        else ""
    )
    fmt = {
        "Feature Service": "ArcGIS service",
        "Shapefile": "Shapefile",
        "CSV Collection": "CSV",
        "Microsoft Excel": "Excel",
        "CSV": "CSV",
        "GeoJson": "GeoJSON",
    }[item["type"]]
    downloads = (
        []
        if item["type"] == "Feature Service"
        else [
            dict(
                format=fmt,
                url=f"https://www.arcgis.com/sharing/rest/content/items/{item['id']}/data",
            )
        ]
    )
    row: JsonObject = dict(
        id="ons:" + item["id"],
        title=title,
        levels=ids,
        kind=kind,
        vintage=vintage,
        year=year,
        years=years,
        countries=countries,
        variant=boundary_variant(title),
        provider="ons",
        type=item["type"],
        formats=[fmt],
        downloads=downloads,
        source="https://geoportal.statistics.gov.uk/datasets/" + item["id"] + "/about",
        itemUrl="https://ons.maps.arcgis.com/home/item.html?id=" + item["id"],
        service=item.get("url") or "",
        published=_date_prefix(item["created"]),
        modified=_date_prefix(item["modified"]),
        method=method,
        uploaded=timestamp(item.get("created")),
        infoUpdated=timestamp(item.get("modified")),
        access="Public source",
        dateBasis="Title-labelled reference vintage" if years else "Unlabelled",
        notes="",
        checked=datetime.now(timezone.utc).date().isoformat(),
    )
    if kind == "centroid":
        row["centroidWeight"] = centroid_weight(title, kind)
        row["centroidWeightBasis"] = (
            "Not specified by the indexed source"
            if row["centroidWeight"] == "not-specified"
            else "Title-labelled method; check publisher methodology"
        )
    return row


def verify_sources(records: list[JsonObject]) -> None:
    """Check landing pages only. Large GIS files are never fetched."""

    def check(url: str) -> JsonObject:
        """Report a bounded landing-page request without interrupting other checks."""
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "UK-Boundary-Atlas source check"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                response.read(256)
                return dict(url=url, status=response.status)
        # A failed publisher page must be reported alongside the other sources.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return dict(url=url, error=str(exc))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, sorted({x["source"] for x in records})))
    for result in results:
        print(json.dumps(result))
    if any("error" in r for r in results):
        raise RuntimeError(
            "A curated source failed; existing catalogue has not been replaced."
        )


def build(
    raw: list[JsonObject], metadata: JsonObject | None = None, ons_checked: str | None = None
) -> JsonObject:
    """Combine publisher items, curated sources and audited overrides.

    Parameters
    ----------
    raw : list of dict
        Complete ONS item listing; no features or polygons are expected.
    metadata : dict or None
        Captured service schemas, availability and dates, keyed by record ID.
    ons_checked : str or None
        Original scan date when rebuilding from a saved ONS listing.

    Returns
    -------
    dict
        Sorted catalogue with taxonomy and source provenance. Duplicate IDs raise
        RuntimeError. Curated records keep their audited dates and methods.
    """
    registry = json.loads((ROOT / "source_records.json").read_text(encoding="utf-8"))
    rows = [r for item in raw if (r := normalize_ons(item))] + registry["items"]
    if ons_checked:
        for row in rows:
            if row["provider"] == "ons":
                row["checked"] = ons_checked
    audit = json.loads((ROOT / "metadata_overrides.json").read_text(encoding="utf-8"))
    snapshots = {x["vintage"]: x for x in audit["authoritySnapshots"]}
    for row in rows:
        if row["kind"] == "centroid":
            row.setdefault("centroidWeight", centroid_weight(row["title"], row["kind"]))
            row.setdefault(
                "centroidWeightBasis",
                "Not specified by the indexed source"
                if row["centroidWeight"] == "not-specified"
                else "Title-labelled method; check publisher methodology",
            )
        row.update(audit["records"].get(row["id"], {}))
        if (
            row["kind"] == "boundary"
            and "combined" in row["levels"]
            and row["vintage"] in snapshots
        ):
            snapshot = snapshots[row["vintage"]]
            row["areas"] = snapshot["areas"]
            row["areaNamesSource"] = snapshot["source"]
            row["areaNamesChecked"] = snapshot["checked"]
            if (
                any(x["code"] in audit["ccaCodes"] for x in row["areas"])
                and "cca" not in row["levels"]
            ):
                row["levels"].append("cca")
            row["notes"] = (
                "Shared combined-authority file, including CCA features where "
                "present. Indexed names/codes were checked against this vintage. "
                "Mayoral status is not inferred from a boundary file."
            )
    for row in rows:
        apply_metadata(row, (metadata or {}).get("records", {}).get(row["id"]))
    if len({x["id"] for x in rows}) != len(rows):
        raise RuntimeError("Duplicate catalogue ids")
    rows.sort(key=lambda x: (-max(x["years"], default=0), x["title"].casefold(), x["id"]))
    return dict(
        schemaVersion=2,
        checked=datetime.now(timezone.utc).date().isoformat(),
        historyStart=2010,
        historyEnd=YEAR,
        levels=LEVELS,
        providers=PROVIDERS,
        curatedChecked=registry["checked"],
        items=rows,
        sourceAudit=dict(
            onsItemsScanned=len(raw),
            onsMetadataChecked=ons_checked or datetime.now(timezone.utc).date().isoformat(),
            publisherMetadataChecked=(metadata or {}).get("checked"),
            curatedRecords=len(registry["items"]),
            scope="Official metadata and curated national sources. No GIS file mirror.",
        ),
    )


def write_catalogue(payload: JsonObject, path: str | Path) -> None:
    """One metadata record per line keeps refresh diffs reviewable."""
    header = {k: v for k, v in payload.items() if k != "items"}
    text = json.dumps(header, ensure_ascii=False, indent=2)[:-2] + ',\n  "items": [\n'
    text += (
        ",\n".join("    " + json.dumps(x, ensure_ascii=False) for x in payload["items"])
        + "\n  ]\n}\n"
    )
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    """Run the existing ingestion CLI and write the generated metadata snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ons-cache", type=Path, help="Rebuild from a saved raw ONS metadata array"
    )
    parser.add_argument(
        "--ons-checked", help="Original YYYY-MM-DD scan date when rebuilding from a raw cache"
    )
    parser.add_argument(
        "--verify-sources", action="store_true", help="Check curated source landing pages"
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help=(
            "Capture public ArcGIS layer schemas, download flags and publisher "
            "dates (no geometry)"
        ),
    )
    args = parser.parse_args()
    if args.ons_cache and not args.ons_checked:
        parser.error(
            "--ons-cache requires --ons-checked so cached item metadata is not "
            "labelled freshly scanned"
        )
    if args.ons_checked:
        try:
            datetime.strptime(args.ons_checked, "%Y-%m-%d")
        except ValueError:
            parser.error("--ons-checked must be YYYY-MM-DD")
    if args.verify_sources:
        verify_sources(
            json.loads((ROOT / "source_records.json").read_text(encoding="utf-8"))["items"]
        )
    raw = (
        json.loads(args.ons_cache.read_text(encoding="utf-8"))
        if args.ons_cache
        else fetch_ons()
    )
    cache_path = ROOT / "dist" / "dataset-metadata.json"
    metadata = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else None
    )
    if args.refresh_metadata:
        metadata = refresh_metadata(build(raw)["items"], metadata)
        write_metadata(metadata, cache_path)
    payload = build(raw, metadata, args.ons_checked if args.ons_cache else None)
    write_catalogue(payload, ROOT / "dist" / "catalogue.json")
    print("Saved", len(payload["items"]), "records across", len(LEVELS), "reporting levels.")


if __name__ == "__main__":
    main()
