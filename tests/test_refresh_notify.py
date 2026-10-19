"""Exercise issue notifications offline, including failed and repeated runs."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import refresh_notify

REPOSITORY = "hulsiejames/uk-boundaries"
RUN_ID = "12345"
ISSUE_URL = f"https://github.com/{REPOSITORY}/issues/42"


def report():
    return dict(
        status="checked",
        errors=[],
        finished="2026-10-19T10:06:28Z",
        summary={key: 0 for key in refresh_notify.SUMMARY_FIELDS},
    )


def captured():
    return dict(checked=True, finished=report()["finished"], summary=report()["summary"])


def existing_issue(body, **extra):
    return dict(
        number=42,
        html_url=ISSUE_URL,
        body=body,
        title="Previous title",
        user=dict(login="github-actions[bot]"),
        **extra,
    )


class NotificationTests(unittest.TestCase):
    def test_capture_requires_checked_complete_candidate_and_numeric_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "refresh-status.json"
            for name in ("catalogue.json", "dataset-metadata.json"):
                (directory / name).write_text("{}", encoding="utf-8")
            path.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(refresh_notify.capture_report(path), captured())
            for override in (
                dict(status="rejected"),
                dict(errors=["Capture outage"]),
                dict(finished="not a date"),
                dict(summary={**report()["summary"], "added": True}),
                dict(summary={**report()["summary"], "added": -1}),
                dict(summary={}),
            ):
                with self.subTest(override=override):
                    path.write_text(json.dumps({**report(), **override}), encoding="utf-8")
                    self.assertFalse(refresh_notify.capture_report(path)["checked"])
            path.write_text(json.dumps(report()), encoding="utf-8")
            (directory / "catalogue.json").unlink()
            self.assertFalse(refresh_notify.capture_report(path)["checked"])

    def test_missing_and_malformed_reports_are_unverified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "refresh-status.json"
            self.assertEqual(refresh_notify.capture_report(path), dict(checked=False))
            for text in ("[1, 2]", "{", "null", '{"summary": []}'):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(refresh_notify.capture_report(path), dict(checked=False))

    def test_ready_notice_mentions_owner_links_artifact_and_explains_publication(self):
        title, body = refresh_notify.build_notice(
            REPOSITORY, RUN_ID, "1", "success", captured(), "9"
        )
        self.assertIn("ready for review", title)
        self.assertIn("@hulsiejames", body)
        self.assertIn(f"actions/runs/{RUN_ID}/artifacts/9", body)
        self.assertIn("30 days", body)
        self.assertIn("has not been updated", body)
        self.assertIn("merge the metadata update", body)
        self.assertIn("0 added records", body)
        self.assertIn("dataset-metadata.json", body)

    def test_failed_cancelled_missing_report_or_missing_artifact_never_says_ready(self):
        for result, candidate, artifact in (
            ("failure", captured(), "9"),
            ("cancelled", captured(), "9"),
            ("success", {}, "9"),
            ("success", dict(checked=False), "9"),
            ("success", captured(), ""),
        ):
            with self.subTest(result=result, artifact=artifact):
                title, body = refresh_notify.build_notice(
                    REPOSITORY, RUN_ID, "1", result, candidate, artifact
                )
                self.assertIn("needs attention", title)
                self.assertIn("@hulsiejames", body)
                self.assertIn("Do not publish", body)
                self.assertNotIn("/artifacts/", body)

    def test_context_validation_prevents_invalid_links(self):
        for repository, run_id, attempt in (
            ("https://other.test/a/b", RUN_ID, "1"),
            (REPOSITORY, "123/other", "1"),
            (REPOSITORY, RUN_ID, "@someone"),
        ):
            with self.assertRaises(ValueError):
                refresh_notify.build_notice(
                    repository, run_id, attempt, "success", captured(), "9"
                )

    def test_new_run_creates_issue_with_no_content_or_pr_api_calls(self):
        request = Mock(side_effect=[[], dict(html_url=ISSUE_URL)])
        title, body = refresh_notify.build_notice(
            REPOSITORY, RUN_ID, "1", "success", captured(), "9"
        )
        url = refresh_notify.upsert_issue(REPOSITORY, RUN_ID, title, body, request)
        self.assertEqual(url, ISSUE_URL)
        self.assertEqual(request.call_count, 2)
        method, path, payload = request.call_args.args
        self.assertEqual((method, path), ("POST", f"/repos/{REPOSITORY}/issues"))
        self.assertEqual(payload, dict(title=title, body=body))

    def test_rerun_updates_existing_closed_issue_without_reopening(self):
        title, body = refresh_notify.build_notice(
            REPOSITORY, RUN_ID, "2", "success", captured(), "10"
        )
        previous = existing_issue(
            f"<!-- uk-boundaries:catalogue-refresh:{RUN_ID} -->", state="closed"
        )
        request = Mock(side_effect=[[previous], dict(html_url=ISSUE_URL)])
        self.assertEqual(
            refresh_notify.upsert_issue(REPOSITORY, RUN_ID, title, body, request), ISSUE_URL
        )
        method, path, payload = request.call_args.args
        self.assertEqual(method, "PATCH")
        self.assertTrue(path.endswith("/issues/42"))
        self.assertIn("attempt 2", payload["body"])
        self.assertNotIn("state", payload)

    def test_same_attempt_is_idempotent_and_owner_created_bootstrap_issue_is_reused(self):
        title, body = refresh_notify.build_notice(
            REPOSITORY, RUN_ID, "1", "success", captured(), "9"
        )
        issue = existing_issue(body)
        issue.update(title=title, user=dict(login="hulsiejames"))
        request = Mock(return_value=[issue])
        self.assertEqual(
            refresh_notify.upsert_issue(REPOSITORY, RUN_ID, title, body, request), ISSUE_URL
        )
        request.assert_called_once()

    def test_issue_pagination_skips_prs_and_untrusted_or_other_run_markers(self):
        title, body = refresh_notify.build_notice(
            REPOSITORY, RUN_ID, "1", "success", captured(), "9"
        )
        pr = existing_issue(body, pull_request={})
        untrusted = existing_issue(body)
        untrusted["user"] = dict(login="unrelated-user")
        other_run = existing_issue("<!-- uk-boundaries:catalogue-refresh:123456 -->")
        first_page = [pr, untrusted] + [other_run] * 98
        target = existing_issue(body)
        target["title"] = title
        request = Mock(side_effect=[first_page, [target]])
        refresh_notify.upsert_issue(REPOSITORY, RUN_ID, title, body, request)
        self.assertEqual(request.call_count, 2)
        self.assertIn("state=all", request.call_args.args[1])
        self.assertIn("page=2", request.call_args.args[1])

    def test_prepare_cli_writes_single_json_output_with_unverified_missing_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "github-output"
            with (
                patch.dict(os.environ, GITHUB_OUTPUT=str(output)),
                patch(
                    "sys.argv",
                    ["refresh_notify.py", "--prepare", str(output.parent / "missing")],
                ),
            ):
                refresh_notify.main()
            self.assertEqual(output.read_text(encoding="utf-8"), 'report={"checked":false}\n')

    def test_cli_handles_failure_before_report_and_summarises_issue(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = Path(temporary) / "summary.md"
            environment = dict(
                GITHUB_REPOSITORY=REPOSITORY,
                GITHUB_RUN_ID=RUN_ID,
                GITHUB_RUN_ATTEMPT="1",
                REFRESH_RESULT="failure",
                REFRESH_REPORT="{invalid",
                REFRESH_ARTIFACT_ID="",
                GITHUB_STEP_SUMMARY=str(summary),
            )
            with (
                patch.dict(os.environ, environment),
                patch("sys.argv", ["refresh_notify.py"]),
                patch.object(refresh_notify, "upsert_issue", return_value=ISSUE_URL) as upsert,
                redirect_stdout(io.StringIO()),
            ):
                refresh_notify.main()
            self.assertIn("needs attention", upsert.call_args.args[2])
            self.assertIn("@hulsiejames", summary.read_text(encoding="utf-8"))
            self.assertIn(ISSUE_URL, summary.read_text(encoding="utf-8"))

    def test_http_client_sends_json_to_github_and_does_not_print_token(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, GH_TOKEN="test-token-not-for-logging"),
            patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"ok":true}')) as opener,
            redirect_stdout(output),
        ):
            result = refresh_notify.github_request(
                "POST", "/repos/a/b/issues", dict(body="hello")
            )
        self.assertEqual(result, dict(ok=True))
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/a/b/issues")
        self.assertEqual(
            request.get_header("Authorization"), "Bearer test-token-not-for-logging"
        )
        self.assertEqual(json.loads(request.data), dict(body="hello"))
        self.assertEqual(output.getvalue(), "")

    def test_permission_failure_surfaces_clear_error_instead_of_silently_passing(self):
        environment = dict(
            GITHUB_REPOSITORY=REPOSITORY,
            GITHUB_RUN_ID=RUN_ID,
            GITHUB_RUN_ATTEMPT="1",
            REFRESH_RESULT="failure",
            REFRESH_REPORT="",
            REFRESH_ARTIFACT_ID="",
        )
        error = urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, None)
        with (
            patch.dict(os.environ, environment),
            patch("sys.argv", ["refresh_notify.py"]),
            patch.object(refresh_notify, "upsert_issue", side_effect=error),
            self.assertRaisesRegex(SystemExit, "HTTP 403.*issues: write"),
        ):
            refresh_notify.main()


if __name__ == "__main__":
    unittest.main()
