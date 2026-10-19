"""Protect catalogue selection, native downloads, safe extraction and atomic outputs."""

import io
import json
import sqlite3
import stat
import struct
import tempfile
import unittest
import urllib.error
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from uk_boundaries import (
    AmbiguousLayerError,
    BoundaryError,
    Catalogue,
    DownloadUnavailableError,
)


class Response:
    def __init__(self, data, *, status=200, headers=None, url="https://example.org/file"):
        self.data = io.BytesIO(data)
        self.status = status
        self.headers = headers or {}
        self.url = url
        self.closed = False

    def read(self, amount):
        return self.data.read(amount)

    def geturl(self):
        return self.url

    def close(self):
        self.closed = True


def record(**changes):
    row = dict(
        id="ons:" + "a" * 32,
        title="Local Authorities (2011) Boundaries UK BFC",
        levels=["lad"],
        countries=["England", "Wales", "Scotland", "Northern Ireland"],
        years=[2011],
        kind="boundary",
        variant="BFC",
        source="https://example.org/about",
        service="",
        downloads=[],
        checked="2026-10-10",
    )
    row.update(changes)
    return row


def catalogue(rows):
    return Catalogue(
        dict(
            checked="2026-10-10",
            items=rows,
            levels=[
                dict(id=level, label=level, aliases=[]) for level in ("lad", "oa-ew", "msoa")
            ],
        )
    )


def archive(files, *, compress=False):
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    ) as bundle:
        for name, value in files.items():
            bundle.writestr(name, value)
    return output.getvalue()


class CatalogueSelection(unittest.TestCase):
    def test_reference_years_country_coverage_variants_and_oa_search_are_distinct(self):
        rows = [
            record(id="oa", title="OA (2011) Boundaries", levels=["oa-ew"]),
            record(id="msoa", title="MSOA (2021) Boundaries", levels=["msoa"], years=[2021]),
            record(
                id="lookup", title="2011 to 2021 Lookup", kind="lookup", years=[2011, 2021]
            ),
        ]
        cat = catalogue(rows)
        self.assertEqual([d.id for d in cat.search("OA", country="Wales", year=2011)], ["oa"])
        self.assertEqual(
            [d.id for d in cat.search(level="msoa", year=2021, variant="bfc")], ["msoa"]
        )
        self.assertEqual([d.id for d in cat.search(kind="lookup", year=2021)], ["lookup"])
        with self.assertRaises(ValueError):
            cat.search(level="misspelt")

    def test_local_loading_and_get_do_not_fetch_or_mutate_the_catalogue(self):
        row = record()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalogue.json"
            path.write_text(json.dumps(dict(items=[row], levels=[])), encoding="utf-8")
            with patch(
                "urllib.request.urlopen", side_effect=AssertionError("Unexpected network")
            ):
                cat = Catalogue.from_file(path)
                selected = cat.get(row["id"])
                selected.record["title"] = "Changed by caller"
                self.assertNotEqual(cat.get(row["id"]).record["title"], "Changed by caller")
            with self.assertRaises(KeyError):
                cat.get("unknown")

    def test_malformed_catalogue_or_duplicate_ids_are_rejected(self):
        for data in [{}, dict(items=[{}]), dict(items=[record(), record()])]:
            with self.subTest(data=data), self.assertRaises(BoundaryError):
                Catalogue(data)


class PublisherResolution(unittest.TestCase):
    def setUp(self):
        self.row = record(service="https://example.org/FeatureServer")
        self.cat = catalogue([self.row])

    def metadata(self, url, *, timeout):
        if url.endswith("FeatureServer?f=json"):
            return dict(layers=[dict(id=7)], tables=[])
        if "/api/v3/" in url:
            return dict(data=dict(attributes=dict(downloadable=True)))
        return dict(
            geometryType="esriGeometryPolygon", supportedExportFormats="geoPackage,shapefile"
        )

    def test_actual_nonzero_layer_is_used_for_both_native_export_formats(self):
        with patch("uk_boundaries.downloads.read_json", side_effect=self.metadata) as read:
            options = self.cat.resolve(self.row["id"])
        self.assertEqual([o.format for o in options], ["gpkg", "shapefile"])
        self.assertTrue(all(o.url.endswith("layers=7") for o in options))
        self.assertTrue(any("/7?f=json" in c.args[0] for c in read.call_args_list))
        self.assertFalse(any("/0?" in c.args[0] for c in read.call_args_list))

    def test_multilayer_service_requires_selection(self):
        with patch(
            "uk_boundaries.downloads.read_json",
            return_value=dict(layers=[dict(id=7), dict(id=12)]),
        ):
            with self.assertRaises(AmbiguousLayerError):
                self.cat.resolve(self.row["id"])

    def test_explicit_service_layer_remains_explicit(self):
        row = record(service="https://example.org/FeatureServer/7")
        with patch("uk_boundaries.downloads.read_json", side_effect=self.metadata):
            self.assertEqual(catalogue([row]).resolve(row["id"])[0].layer_id, 7)
            with self.assertRaises(ValueError):
                catalogue([row]).resolve(row["id"], layer_id=0)

    def test_capabilities_do_not_override_a_disabled_publisher_download(self):
        def metadata(url, *, timeout):
            if "/api/v3/" in url:
                return dict(data=dict(attributes=dict(downloadable=False)))
            return self.metadata(url, timeout=timeout)

        with patch("uk_boundaries.downloads.read_json", side_effect=metadata):
            with self.assertRaises(DownloadUnavailableError):
                self.cat.resolve(self.row["id"])

    def test_direct_file_survives_an_unavailable_optional_service(self):
        row = record(
            service="https://example.org/FeatureServer",
            downloads=[dict(format="Shapefile", url="https://example.org/file.zip")],
        )
        with patch(
            "uk_boundaries.downloads.read_json", side_effect=BoundaryError("Unavailable")
        ):
            self.assertEqual(catalogue([row]).resolve(row["id"])[0].format, "shapefile")


class NativeDownloads(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "downloads"
        self.gpkg_path = self.root / "fixture.gpkg"
        with closing(sqlite3.connect(self.gpkg_path)) as database, database:
            for name in (
                "gpkg_contents",
                "gpkg_spatial_ref_sys",
                "gpkg_geometry_columns",
                "features",
            ):
                database.execute(f"CREATE TABLE {name} (code TEXT)")
            database.execute("INSERT INTO features VALUES ('AREA001')")
        self.gpkg = self.gpkg_path.read_bytes()
        self.shape = archive(
            {
                "boundary/areas.shp": struct.pack(">i", 9994) + b"\x00" * 96,
                "boundary/areas.shx": struct.pack(">i", 9994) + b"\x00" * 96,
                "boundary/areas.dbf": b"\x03" + b"\x00" * 31,
                "boundary/areas.prj": b"publisher CRS definition",
            }
        )
        self.row = record(
            downloads=[
                dict(format="GeoPackage", url="https://example.org/data.gpkg"),
                dict(format="Shapefile", url="https://example.org/data.zip"),
            ]
        )
        self.cat = catalogue([self.row])

    def test_geopackage_is_preferred_and_provenance_omits_signed_redirect_tokens(self):
        response = Response(
            self.gpkg, url="https://storage.example.org/file?X-Amz-Signature=private"
        )
        with patch("urllib.request.urlopen", return_value=response):
            result = self.cat.download(self.row["id"], self.output)
        self.assertEqual(result.format, "gpkg")
        self.assertEqual(result.path.read_bytes(), self.gpkg)
        manifest = json.loads(result.manifest_path.read_text())
        self.assertEqual(manifest["reference_years"], [2011])
        self.assertEqual(manifest["catalogue_checked"], "2026-10-10")
        self.assertNotIn("private", result.manifest_path.read_text())
        self.assertTrue(response.closed)

    def test_geopackage_zip_is_unpacked_with_its_native_bytes(self):
        with patch(
            "urllib.request.urlopen", return_value=Response(archive({"areas.gpkg": self.gpkg}))
        ):
            result = self.cat.download(self.row["id"], self.output)
        self.assertEqual(result.path.read_bytes(), self.gpkg)

    def test_missing_preferred_format_falls_back_to_complete_shapefile(self):
        failure = urllib.error.HTTPError(
            "https://example.org/data.gpkg", 404, "Missing", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=[failure, Response(self.shape)]):
            result = self.cat.download(self.row["id"], self.output)
        self.assertEqual(result.format, "shapefile")
        self.assertEqual(result.path.suffix, ".shp")
        self.assertTrue(result.path.with_suffix(".dbf").exists())
        self.assertTrue(result.path.with_suffix(".shx").exists())
        self.assertEqual(
            len(json.loads(result.manifest_path.read_text())["failed_attempts"]), 1
        )

    def test_queued_export_is_polled_until_a_file_is_returned(self):
        waiting = Response(
            b'{"status":"pending"}',
            status=202,
            headers={
                "Location": "https://example.org/status",
                "Content-Type": "application/json",
            },
        )
        with (
            patch(
                "urllib.request.urlopen", side_effect=[waiting, Response(self.gpkg)]
            ) as request,
            patch("uk_boundaries.downloads.time.sleep"),
        ):
            result = self.cat.download(self.row["id"], self.output)
        self.assertEqual(result.format, "gpkg")
        self.assertEqual(
            request.call_args_list[1].args[0].full_url, "https://example.org/status"
        )

    def test_failed_or_truncated_download_does_not_replace_a_successful_output(self):
        with patch("urllib.request.urlopen", return_value=Response(self.gpkg)):
            result = self.cat.download(
                self.row["id"], self.output, format_preference=("gpkg",)
            )
        before = result.path.read_bytes()
        bad = Response(b"short", headers={"Content-Length": "1000"})
        with (
            patch("urllib.request.urlopen", return_value=bad),
            self.assertRaises(DownloadUnavailableError),
        ):
            self.cat.download(
                self.row["id"], self.output, overwrite=True, format_preference=("gpkg",)
            )
        self.assertEqual(result.path.read_bytes(), before)
        with (
            patch("urllib.request.urlopen", side_effect=AssertionError("Must not overwrite")),
            self.assertRaises(FileExistsError),
        ):
            self.cat.download(self.row["id"], self.output, format_preference=("gpkg",))

    def test_failed_atomic_publish_restores_existing_output(self):
        with patch("urllib.request.urlopen", return_value=Response(self.gpkg)):
            result = self.cat.download(
                self.row["id"], self.output, format_preference=("gpkg",)
            )
        original_rename = Path.rename

        def rename(path, target):
            if path.name == "content":
                raise PermissionError("Simulated output rename failure")
            return original_rename(path, target)

        with (
            patch("urllib.request.urlopen", return_value=Response(self.gpkg)),
            patch.object(Path, "rename", rename),
            self.assertRaises(DownloadUnavailableError),
        ):
            self.cat.download(
                self.row["id"], self.output, overwrite=True, format_preference=("gpkg",)
            )
        self.assertEqual(result.path.read_bytes(), self.gpkg)

    def test_unsafe_archive_paths_are_rejected_before_extraction(self):
        for name in (
            "../outside.gpkg",
            "/outside.gpkg",
            "C:/outside.gpkg",
            "CON",
            "a/../outside.gpkg",
            "a./outside.gpkg",
        ):
            with (
                self.subTest(name=name),
                patch(
                    "urllib.request.urlopen", return_value=Response(archive({name: self.gpkg}))
                ),
                self.assertRaises(DownloadUnavailableError),
            ):
                self.cat.download(self.row["id"], self.output, format_preference=("gpkg",))
        self.assertFalse((self.root / "outside.gpkg").exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_incomplete_shapefile_and_html_error_page_are_not_saved(self):
        responses = [
            Response(b"<html>Portal error</html>"),
            Response(archive({"areas.shp": b"not a shapefile"})),
        ]
        with (
            patch("urllib.request.urlopen", side_effect=responses),
            self.assertRaises(DownloadUnavailableError),
        ):
            self.cat.download(self.row["id"], self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_transfer_and_uncompressed_size_limits_are_enforced(self):
        for payload, maximum in [
            (self.gpkg, 100),
            (archive({"large.gpkg": self.gpkg}, compress=True), 2000),
        ]:
            with (
                self.subTest(maximum=maximum),
                patch("urllib.request.urlopen", return_value=Response(payload)),
                self.assertRaises(DownloadUnavailableError),
            ):
                self.cat.download(
                    self.row["id"], self.output, format_preference=("gpkg",), max_bytes=maximum
                )

    def test_multifile_bundle_requires_explicit_path_selection(self):
        bundle = archive({"one.gpkg": self.gpkg, "two.gpkg": self.gpkg})
        with patch("urllib.request.urlopen", return_value=Response(bundle)):
            result = self.cat.download(self.row["id"], self.output)
        self.assertEqual(len(result.paths), 2)
        with self.assertRaises(AmbiguousLayerError):
            _ = result.path

    def test_unsupported_format_or_page_only_source_is_an_explicit_failure(self):
        with self.assertRaises(ValueError):
            self.cat.download(self.row["id"], self.output, format_preference=("csv",))
        row = record()
        with self.assertRaises(DownloadUnavailableError):
            catalogue([row]).download(row["id"], self.output)

    def test_queued_export_obeys_the_preparation_deadline(self):
        waiting = Response(b'{"status":"pending"}', status=202)
        with (
            patch("urllib.request.urlopen", return_value=waiting),
            patch("uk_boundaries.downloads.time.monotonic", side_effect=[0, 0, 0, 2]),
            patch("uk_boundaries.downloads.time.sleep"),
            self.assertRaisesRegex(DownloadUnavailableError, "Timed out"),
        ):
            self.cat.download(
                self.row["id"], self.output, max_wait=1, format_preference=("gpkg",)
            )

    def test_duplicate_archive_paths_and_symlinks_are_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as bundle:
            link = zipfile.ZipInfo("link.gpkg")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(link, "../outside.gpkg")
        payloads = [
            output.getvalue(),
            archive({"areas.gpkg": self.gpkg, "AREAS.gpkg": self.gpkg}),
        ]
        for payload in payloads:
            with (
                self.subTest(payload_size=len(payload)),
                patch("urllib.request.urlopen", return_value=Response(payload)),
                self.assertRaises(DownloadUnavailableError),
            ):
                self.cat.download(self.row["id"], self.output, format_preference=("gpkg",))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_successful_overwrite_replaces_only_the_selected_dataset_directory(self):
        with patch("urllib.request.urlopen", return_value=Response(self.gpkg)):
            result = self.cat.download(
                self.row["id"], self.output, format_preference=("gpkg",)
            )
        untouched = self.output / "another-process.txt"
        untouched.write_text("keep", encoding="utf-8")
        with closing(sqlite3.connect(self.gpkg_path)) as database, database:
            database.execute("UPDATE features SET code='AREA002'")
        updated = self.gpkg_path.read_bytes()
        with patch("urllib.request.urlopen", return_value=Response(updated)):
            replacement = self.cat.download(
                self.row["id"], self.output, overwrite=True, format_preference=("gpkg",)
            )
        self.assertEqual(result.path, replacement.path)
        self.assertEqual(replacement.path.read_bytes(), updated)
        self.assertEqual(untouched.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
