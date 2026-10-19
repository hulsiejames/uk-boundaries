"""Download 2021 OA population-weighted centroids and subset Greater Manchester.

Run from a checkout with the package and optional example dependencies installed::

    python -m examples.greater_manchester --catalogue dist/catalogue.json

The boundary is the December 2021 Greater Manchester combined authority,
E47000001. Dataset selection and downloads use the public uk_boundaries API.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd

from uk_boundaries import Catalogue, Dataset, DownloadResult

GREATER_MANCHESTER_CODE = "E47000001"
REFERENCE_YEAR = 2021


def unique_match(matches: list[Dataset], description: str) -> Dataset:
    """Require one matching source instead of silently picking a file or version."""
    if len(matches) != 1:
        choices = "; ".join(f"{row.id}: {row.title}" for row in matches) or "none"
        raise ValueError(f"Expected one {description}; found {len(matches)}: {choices}")
    return matches[0]


def select_datasets(catalogue: Catalogue) -> tuple[Dataset, Dataset]:
    """Search for population-weighted OAs and a matching-year BFC authority file."""
    centroids = [
        row
        for row in catalogue.search(
            level="oa-ew", country="England", year=REFERENCE_YEAR, kind="centroid"
        )
        if row.record.get("centroidWeight") == "population" and row.years == (REFERENCE_YEAR,)
    ]
    boundaries = catalogue.search(
        GREATER_MANCHESTER_CODE,
        level="combined",
        country="England",
        year=REFERENCE_YEAR,
        kind="boundary",
        variant="BFC",
    )
    return (
        unique_match(centroids, "2021 OA population-weighted centroid dataset"),
        unique_match(boundaries, "2021 BFC Greater Manchester authority dataset"),
    )


def select_authority(boundaries: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Select exactly one Greater Manchester feature using its official GSS code."""
    code_fields = [name for name in boundaries.columns if re.fullmatch(r"CAUTH\d{2}CD", name)]
    if len(code_fields) != 1:
        raise ValueError(f"Expected one CAUTHxxCD authority code field; found {code_fields}")
    selected = boundaries.loc[boundaries[code_fields[0]] == GREATER_MANCHESTER_CODE].copy()
    if len(selected) != 1:
        raise ValueError(
            f"Expected one {GREATER_MANCHESTER_CODE} feature; found {len(selected)}"
        )
    return selected


def subset_centroids(
    points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, int]:
    """Select points strictly within a polygon, retaining source point fields and CRS.

    Both inputs must have a CRS and valid, nonempty geometry. The boundary must
    contain exactly one Polygon or MultiPolygon. It is reprojected to the point
    CRS before querying the point spatial index. Polygon ``contains(point)`` is
    the inverse of point ``within(polygon)``; points exactly on the edge are
    excluded and counted separately.

    Returns
    -------
    selected, aligned_boundary, edge_count
        Selected points in original row order, the boundary in the point CRS,
        and the number of points exactly touching the boundary.
    """
    if points.crs is None or boundary.crs is None:
        raise ValueError("Both spatial inputs must declare a CRS")
    for frame, allowed in ((points, ["Point"]), (boundary, ["Polygon", "MultiPolygon"])):
        if (
            frame.empty
            or not frame.geometry.geom_type.isin(allowed).all()
            or not frame.geometry.is_valid.all()
            or frame.geometry.is_empty.any()
        ):
            raise ValueError("Expected nonempty, valid point and polygon geometries")
    if len(boundary) != 1:
        raise ValueError("Select exactly one authority feature before the spatial subset")
    aligned = boundary.to_crs(points.crs)
    if not aligned.geometry.is_valid.all():
        raise ValueError("Boundary became invalid after reprojection")
    polygon = aligned.geometry.iloc[0]
    positions = points.sindex.query(polygon, predicate="contains", sort=True)
    edge_count = len(points.sindex.query(polygon, predicate="touches"))
    return points.iloc[positions].copy(), aligned, edge_count


def read_download(result: DownloadResult) -> gpd.GeoDataFrame:
    """Read one spatial layer, refusing ambiguous multi-file or multi-layer inputs."""
    layers = gpd.list_layers(result.path)
    if len(layers) != 1:
        raise ValueError(f"Expected one layer in {result.path}; found {len(layers)}")
    return gpd.read_file(result.path, layer=layers.iloc[0]["name"], engine="pyogrio")


def write_layer(frame: gpd.GeoDataFrame, target: Path, layer: str) -> None:
    """Write source fields with a separate, unused GeoPackage primary-key name."""
    primary_key = "atlas_fid"
    fields = {name.casefold() for name in frame.columns}
    while primary_key in fields:
        primary_key = "_" + primary_key
    frame.to_file(
        target,
        layer=layer,
        driver="GPKG",
        engine="pyogrio",
        index=False,
        layer_options={"FID": primary_key},
    )


def process_downloads(
    centroids: DownloadResult, boundaries: DownloadResult, output_dir: Path
) -> dict[str, object]:
    """Read publisher files, subset points and write a two-layer GeoPackage."""
    points = read_download(centroids)
    if "OA21CD" not in points or points["OA21CD"].isna().any():
        raise ValueError("The centroid file must contain non-null OA21CD identifiers")
    if points["OA21CD"].duplicated().any():
        raise ValueError("Duplicate OA21CD identifiers in the centroid file")
    authority = select_authority(read_download(boundaries))
    selected, aligned, edge_count = subset_centroids(points, authority)
    if selected.empty:
        raise ValueError("No OA centroids fall within Greater Manchester")
    target = output_dir / "greater_manchester_oa2021.gpkg"
    write_layer(selected, target, "oa2021_pwc")
    write_layer(aligned, target, "greater_manchester_boundary")
    return {
        "authority_code": GREATER_MANCHESTER_CODE,
        "reference_year": REFERENCE_YEAR,
        "predicate": "within (strict interior; boundary points excluded)",
        "input_centroids": len(points),
        "selected_centroids": len(selected),
        "boundary_centroids_excluded": edge_count,
        "output_crs": str(selected.crs),
        "geopackage": target.name,
        "layers": ["oa2021_pwc", "greater_manchester_boundary"],
    }


def run_example(catalogue: Catalogue, output_dir: Path) -> dict[str, object]:
    """Download through the API and publish outputs only after the example succeeds.

    The destination must not exist. Downloads, their provenance manifests, the
    spatial output and a processing report are staged together beside it.
    """
    if output_dir.exists():
        raise FileExistsError(f"Choose a new output directory; already exists: {output_dir}")
    centroid_record, boundary_record = select_datasets(catalogue)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".gm-example-", dir=output_dir.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        downloads = []
        sources = []
        for record in (centroid_record, boundary_record):
            print(f"Downloading {record.id}: {record.title}", flush=True)
            downloaded = catalogue.download(record.id, stage / "downloads")
            downloads.append(downloaded)
            sources.append(
                {
                    "record_id": record.id,
                    "title": record.title,
                    "reference_years": list(record.years),
                    "source": record.source,
                    "format": downloaded.format,
                    "manifest": downloaded.manifest_path.relative_to(stage).as_posix(),
                }
            )
            print(f"Saved publisher {downloaded.format}", flush=True)
        report = process_downloads(downloads[0], downloads[1], stage)
        report.update(
            catalogue_checked=catalogue.checked,
            processed_at=datetime.now(timezone.utc).isoformat(),
            sources=sources,
        )
        (stage / "processing-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        stage.rename(output_dir)
    print(f"Selected {report['selected_centroids']} OA centroids; outputs: {output_dir}")
    return report


def main() -> None:
    """Run against the published snapshot or an explicitly supplied local catalogue."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue", type=Path, help="Local catalogue; default: published site"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("work/greater-manchester"),
        help="New destination directory (default: work/greater-manchester)",
    )
    args = parser.parse_args()
    catalogue = Catalogue.from_file(args.catalogue) if args.catalogue else Catalogue.from_url()
    run_example(catalogue, args.output_dir)


if __name__ == "__main__":
    main()
