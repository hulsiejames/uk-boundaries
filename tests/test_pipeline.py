"""Exercise the script entry points without network access or published-data writes."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import ingest
import refresh


class PipelineCompatibility(unittest.TestCase):
    """Protect CLI output, metadata association and rejected-refresh retention."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "dist").mkdir()
        self.raw = [
            dict(
                id="example",
                title="Local Authority Districts (December 2011) Boundaries UK BFC",
                type="Feature Service",
                created=1777451050000,
                modified=1777451050000,
                url="https://example.org/FeatureServer",
            )
        ]
        self.metadata = dict(
            schemaVersion=1,
            checked="2026-10-10",
            records={
                "ons:example": dict(
                    service="https://example.org/FeatureServer",
                    checked="2026-10-10",
                    status="captured",
                    errors=[],
                    layers=[
                        dict(
                            id=7,
                            fields=[dict(name="CODE", type="esriFieldTypeString")],
                            downloadable=True,
                            downloadSource="https://example.org/metadata",
                            downloadPage="https://example.org/downloads",
                        )
                    ],
                )
            },
        )
        self.write("source_records.json", dict(checked="2026-10-06", items=[]))
        self.write(
            "metadata_overrides.json", dict(authoritySnapshots=[], records={}, ccaCodes=[])
        )
        self.write("ons-cache.json", self.raw)
        self.write("dist/dataset-metadata.json", self.metadata)
        with patch.object(ingest, "ROOT", self.root):
            self.write(
                "dist/catalogue.json",
                ingest.build(self.raw, copy.deepcopy(self.metadata), "2026-10-10"),
            )

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def read(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def run_refresh(self, *, apply=False, reject=False):
        argv = ["refresh.py", "--output-dir", str(self.root / "candidate")]
        if apply:
            argv.append("--apply")
        check_links = refresh.check_links
        with ExitStack() as stack:
            stack.enter_context(patch.object(ingest, "ROOT", self.root))
            stack.enter_context(patch.object(refresh, "ROOT", self.root))
            stack.enter_context(patch("sys.argv", argv))
            stack.enter_context(patch.object(refresh, "fetch_ons", return_value=self.raw))
            stack.enter_context(
                patch.object(
                    refresh, "refresh_metadata", return_value=copy.deepcopy(self.metadata)
                )
            )
            stack.enter_context(
                patch.object(
                    refresh,
                    "check_links",
                    side_effect=lambda candidate, metadata: check_links(
                        candidate, metadata, lambda url: dict(state="reachable", code=200)
                    ),
                )
            )
            if reject:
                stack.enter_context(
                    patch.object(
                        refresh, "validate_candidate", return_value=["Capture outage"]
                    )
                )
            stack.enter_context(
                patch(
                    "urllib.request.urlopen", side_effect=AssertionError("Unexpected network")
                )
            )
            stack.enter_context(redirect_stdout(io.StringIO()))
            refresh.main()

    def test_cached_ingest_cli_preserves_vintage_schema_and_original_scan_date(self):
        argv = [
            "ingest.py",
            "--ons-cache",
            str(self.root / "ons-cache.json"),
            "--ons-checked",
            "2026-10-10",
        ]
        with (
            patch.object(ingest, "ROOT", self.root),
            patch("sys.argv", argv),
            patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")),
            redirect_stdout(io.StringIO()),
        ):
            ingest.main()
        catalogue = self.read("dist/catalogue.json")
        row = catalogue["items"][0]
        self.assertEqual(row["year"], 2011)
        self.assertEqual(row["attributes"]["fields"], 1)
        self.assertEqual(row["attributes"]["checked"], "2026-10-10")
        self.assertEqual(row["downloadAvailability"]["status"], "publisher")
        self.assertEqual(catalogue["sourceAudit"]["onsMetadataChecked"], "2026-10-10")

    def test_report_only_refresh_does_not_modify_published_files(self):
        before = (self.root / "dist/catalogue.json").read_bytes()
        self.run_refresh()
        self.assertEqual((self.root / "dist/catalogue.json").read_bytes(), before)
        self.assertEqual(self.read("candidate/refresh-status.json")["status"], "checked")
        self.assertTrue((self.root / "candidate/summary.md").is_file())

    def test_apply_refresh_publishes_a_consistent_metadata_candidate(self):
        self.run_refresh(apply=True)
        catalogue = self.read("dist/catalogue.json")
        row = catalogue["items"][0]
        self.assertEqual(row["year"], 2011)
        self.assertEqual(row["sourceListing"], "present")
        self.assertEqual(row["linkHealth"]["state"], "checked")
        self.assertEqual(self.read("dist/dataset-metadata.json"), self.metadata)
        self.assertEqual(self.read("dist/refresh-status.json")["summary"]["records"], 1)
        self.assertNotIn("_linkChecks", row)

    def test_rejected_apply_keeps_published_files_and_writes_a_rejection_report(self):
        before = {path.name: path.read_bytes() for path in (self.root / "dist").iterdir()}
        with self.assertRaisesRegex(SystemExit, "Refresh rejected"):
            self.run_refresh(apply=True, reject=True)
        after = {path.name: path.read_bytes() for path in (self.root / "dist").iterdir()}
        self.assertEqual(after, before)
        self.assertEqual(self.read("candidate/refresh-status.json")["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
