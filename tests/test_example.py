"""Offline regression tests for the optional spatial example."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uk_boundaries import Catalogue, DownloadResult

HAS_SPATIAL = importlib.util.find_spec("geopandas") is not None
if HAS_SPATIAL:
    import geopandas as gpd
    from shapely.geometry import Point, Polygon, box

    from examples.greater_manchester import (
        process_downloads,
        run_example,
        select_authority,
        select_datasets,
        subset_centroids,
        write_layer,
    )


def catalogue_data():
    base = {
        "id": "centroids",
        "title": "Output Areas 2021 population weighted centroids",
        "levels": ["oa-ew"],
        "countries": ["England", "Wales"],
        "years": [2021],
        "kind": "centroid",
        "source": "https://example.test/centroids",
        "centroidWeight": "population",
    }
    return {
        "checked": "2026-10-10",
        "levels": [{"id": name} for name in ("oa-ew", "msoa", "combined")],
        "items": [
            base,
            {**base, "id": "geometric", "centroidWeight": "geometric"},
            {**base, "id": "msoa", "levels": ["msoa"]},
            {**base, "id": "old", "years": [2011]},
            {
                **base,
                "id": "authority",
                "title": "Combined Authorities December 2021 EN BFC",
                "levels": ["combined"],
                "kind": "boundary",
                "variant": "BFC",
                "areas": [{"code": "E47000001", "name": "Greater Manchester"}],
            },
        ],
    }


@unittest.skipUnless(HAS_SPATIAL, "Install the optional examples dependencies")
class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.boundaries = gpd.GeoDataFrame(
            {"CAUTH21CD": ["E47000002", "E47000001"], "CAUTH21NM": ["Other", "Manchester"]},
            geometry=[box(20, 20, 21, 21), box(0, 0, 10, 10)],
            crs="EPSG:3857",
        )
        self.points = gpd.GeoDataFrame(
            {"OA21CD": ["inside", "edge", "outside"], "value": [4, 5, 6]},
            geometry=[Point(1, 1), Point(0, 1), Point(11, 1)],
            crs="EPSG:3857",
            index=[8, 3, 9],
        )

    def test_catalogue_selection_excludes_other_levels_weights_and_years(self):
        points, boundary = select_datasets(Catalogue(catalogue_data()))
        self.assertEqual((points.id, boundary.id), ("centroids", "authority"))
        data = catalogue_data()
        data["items"].append({**data["items"][0], "id": "another_version"})
        with self.assertRaisesRegex(ValueError, "found 2.*another_version"):
            select_datasets(Catalogue(data))
        data = catalogue_data()
        data["items"][-1]["variant"] = "BFE"
        with self.assertRaisesRegex(ValueError, "2021 BFC.*found 0"):
            select_datasets(Catalogue(data))

    def test_snapshot_search_finds_the_documented_records(self):
        catalogue = Catalogue.from_file(
            Path(__file__).resolve().parents[1] / "dist/catalogue.json"
        )
        points, boundary = select_datasets(catalogue)
        self.assertEqual(points.id, "ons:558170d37ab04f34845034db91a86914")
        self.assertEqual(boundary.id, "ons:3f826d170e224924bcf602d2d0d53b3c")

    def test_authority_selection_uses_exact_code_and_rejects_duplicates(self):
        selected = select_authority(self.boundaries)
        self.assertEqual(selected.index.tolist(), [1])
        wrong = self.boundaries.copy()
        wrong["CAUTH21CD"] = ["E47000001", "E47000001"]
        with self.assertRaisesRegex(ValueError, "found 2"):
            select_authority(wrong)
        with self.assertRaisesRegex(ValueError, "code field"):
            select_authority(self.boundaries.drop(columns="CAUTH21CD"))

    def test_strict_within_excludes_edges_and_holes_preserving_attributes(self):
        polygon = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            holes=[[(3, 3), (4, 3), (4, 4), (3, 4)]],
        )
        boundary = gpd.GeoDataFrame(geometry=[polygon], crs=self.points.crs)
        points = gpd.GeoDataFrame(
            {"OA21CD": ["inside", "edge", "outside", "hole"], "value": [4, 5, 6, 7]},
            geometry=[*self.points.geometry, Point(3.5, 3.5)],
            crs=self.points.crs,
            index=[8, 3, 9, 12],
        )
        selected, aligned, edge_count = subset_centroids(points, boundary)
        self.assertEqual(selected["OA21CD"].tolist(), ["inside"])
        self.assertEqual(selected["value"].tolist(), [4])
        self.assertEqual(selected.index.tolist(), [8])
        self.assertEqual(edge_count, 1)
        self.assertEqual(selected.crs, points.crs)
        self.assertEqual(aligned.crs, points.crs)
        self.assertEqual(len(points), 4)

    def test_reprojects_boundary_and_preserves_centroid_coordinates(self):
        boundary = select_authority(self.boundaries).to_crs("EPSG:4326")
        selected, aligned, _ = subset_centroids(self.points, boundary)
        self.assertEqual(selected["OA21CD"].tolist(), ["inside"])
        self.assertEqual(selected.geometry.iloc[0], self.points.geometry.iloc[0])
        self.assertEqual(aligned.crs, self.points.crs)

    def test_missing_crs_invalid_geometries_and_unselected_boundaries_fail(self):
        area = select_authority(self.boundaries)
        with self.assertRaisesRegex(ValueError, "CRS"):
            subset_centroids(self.points.set_crs(None, allow_override=True), area)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            subset_centroids(self.points, self.boundaries)
        invalid = area.copy()
        invalid.geometry = [Polygon([(0, 0), (2, 2), (0, 2), (2, 0)])]
        with self.assertRaisesRegex(ValueError, "valid"):
            subset_centroids(self.points, invalid)
        missing_point = self.points.copy()
        missing_point.loc[8, "geometry"] = None
        with self.assertRaisesRegex(ValueError, "valid"):
            subset_centroids(missing_point, area)

    def fake_download(self, record_id, output_dir):
        destination = Path(output_dir) / record_id
        destination.mkdir(parents=True)
        is_points = record_id == "centroids"
        path = destination / ("points.shp" if is_points else "boundaries.gpkg")
        (self.points if is_points else self.boundaries).to_file(path, index=False)
        manifest = destination / "download-manifest.json"
        manifest.write_text(json.dumps({"record_id": record_id}), encoding="utf-8")
        return DownloadResult(
            record_id=record_id,
            format="shapefile" if is_points else "gpkg",
            directory=destination,
            paths=(path,),
            manifest_path=manifest,
            source_url="https://example.test/download",
        )

    def test_workflow_reads_shapefile_writes_two_layers_and_preserves_provenance(self):
        catalogue = Catalogue(catalogue_data())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result"
            with patch.object(
                catalogue, "download", side_effect=self.fake_download
            ) as download:
                report = run_example(catalogue, output)
            self.assertEqual(download.call_count, 2)
            self.assertEqual(report["selected_centroids"], 1)
            self.assertEqual(report["boundary_centroids_excluded"], 1)
            self.assertEqual(report["catalogue_checked"], "2026-10-10")
            gpkg = output / report["geopackage"]
            points = gpd.read_file(gpkg, layer="oa2021_pwc")
            boundary = gpd.read_file(gpkg, layer="greater_manchester_boundary")
            self.assertEqual(points["OA21CD"].tolist(), ["inside"])
            self.assertEqual(boundary["CAUTH21CD"].tolist(), ["E47000001"])
            self.assertEqual(points.crs, boundary.crs)
            saved = json.loads((output / "processing-report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)
            self.assertEqual(saved["sources"][0]["format"], "shapefile")
            for source in saved["sources"]:
                self.assertTrue((output / source["manifest"]).is_file())
            with patch.object(catalogue, "download") as download:
                with self.assertRaises(FileExistsError):
                    run_example(catalogue, output)
                download.assert_not_called()

    def test_failed_processing_does_not_publish_partial_outputs(self):
        catalogue = Catalogue(catalogue_data())
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result"
            with (
                patch.object(catalogue, "download", side_effect=self.fake_download),
                patch(
                    "examples.greater_manchester.process_downloads",
                    side_effect=ValueError("bad"),
                ),
                self.assertRaisesRegex(ValueError, "bad"),
            ):
                run_example(catalogue, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_processing_rejects_duplicate_oa_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.points["OA21CD"] = ["duplicate"] * 3
            centroids = self.fake_download("centroids", directory / "downloads")
            boundaries = self.fake_download("authority", directory / "downloads")
            with self.assertRaisesRegex(ValueError, "Duplicate OA21CD"):
                process_downloads(centroids, boundaries, directory)

    def test_output_preserves_source_fid_fields_as_attributes(self):
        points = self.points.copy()
        points["FID"] = [10, 20, 30]
        points["atlas_fid"] = [40, 50, 60]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "points.gpkg"
            write_layer(points, output, "points")
            saved = gpd.read_file(output)
            self.assertEqual(saved["FID"].tolist(), [10, 20, 30])
            self.assertEqual(saved["atlas_fid"].tolist(), [40, 50, 60])
            self.assertEqual(saved["OA21CD"].tolist(), points["OA21CD"].tolist())


if __name__ == "__main__":
    unittest.main()
