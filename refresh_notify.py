"""Notify the catalogue maintainer through issues without repository or PR writes."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import cast

from metadata_types import JsonObject

Requester = Callable[[str, str, JsonObject | None], object]
SUMMARY_FIELDS = {
    "records": "source records",
    "added": "added records",
    "changed": "listing/date changes",
    "schemaChanged": "changed schemas, counts or download flags",
    "notListed": "historical ONS records absent from discovery (retained)",
    "missingLinks": "missing HTTP links",
    "restrictedLinks": "restricted HTTP links",
    "inconclusiveLinks": "inconclusive HTTP links",
    "attentionRecords": "records needing attention",
}


def capture_report(path: Path) -> JsonObject:
    """Reduce a candidate report to validated counts and a check timestamp.

    Missing, malformed or rejected reports are represented as unverified. Only
    selected numeric fields cross the job boundary; publisher text is not used
    as workflow code or copied into issue notifications.
    """
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("summary"), dict):
            raise ValueError("Invalid report structure")
        finished = report["finished"]
        datetime.fromisoformat(finished.replace("Z", "+00:00"))
        summary = {key: report["summary"][key] for key in SUMMARY_FIELDS}
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in summary.values()
        ):
            raise ValueError("Invalid summary counts")
        complete = all(
            (path.parent / name).is_file()
            for name in ("catalogue.json", "dataset-metadata.json", "refresh-status.json")
        )
        return dict(
            checked=report.get("status") == "checked"
            and report.get("errors") == []
            and complete,
            finished=finished,
            summary=summary,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return dict(checked=False)


def build_notice(
    repository: str,
    run_id: str,
    attempt: str,
    result: str,
    report: JsonObject,
    artifact_id: str,
) -> tuple[str, str]:
    """Describe a ready candidate only after the entire refresh job succeeded."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not run_id.isdecimal():
        raise ValueError("Expected a GitHub repository and numeric workflow run ID")
    if not attempt.isdecimal():
        raise ValueError("Expected a numeric workflow run attempt")
    ready = result == "success" and report.get("checked") is True and artifact_id.isdecimal()
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    title = (
        "Catalogue update ready for review" if ready else "Catalogue refresh needs attention"
    )
    title += f" (run {run_id})"
    message = (
        "a tested catalogue candidate is ready for review"
        if ready
        else "the catalogue refresh did not produce a verified, tested candidate"
    )
    body = (
        f"<!-- uk-boundaries:catalogue-refresh:{run_id} -->\n\n"
        f"@hulsiejames {message}.\n\n"
        f"[Workflow run, attempt {attempt}]({run_url}/attempts/{attempt}) · "
        f"Refresh job result: **{result}**.\n\n"
        "**The published site has not been updated by this refresh.**\n\n"
    )
    if ready:
        body += f"Source checks completed: {report['finished']}.\n\n"
        body += "\n".join(
            f"- {report['summary'][key]} {label}." for key, label in SUMMARY_FIELDS.items()
        )
        body += (
            f"\n\n[Download catalogue-refresh-report]({run_url}/artifacts/{artifact_id}) "
            "(GitHub sign-in required). Artifacts are retained for **30 days**; "
            "after expiry, run **Actions → Check and refresh catalogue → Run workflow** "
            "to generate a fresh candidate.\n\n"
            "To publish:\n"
            "1. Extract the artifact; review `summary.md` and `refresh-status.json`. "
            "Confirm `status: checked` and no validation errors; "
            "inspect source/link changes.\n"
            "2. In a current checkout of `main`, copy only `catalogue.json`, "
            "`dataset-metadata.json` and `refresh-status.json` into `dist/`.\n"
            "3. Run the Python/Node checks in the README, review and commit those three "
            "files, then merge the metadata update. GitHub Pages deploys from `main`.\n"
            "4. Verify the published snapshot and close this issue.\n"
        )
    else:
        body += (
            "Inspect the workflow logs and any diagnostic artifact in the run. "
            "**Do not publish a rejected or untested candidate.** Fix the failure and "
            "rerun the workflow; reruns update this issue instead of creating duplicates.\n"
        )
    return title, body


def github_request(method: str, path: str, data: JsonObject | None = None) -> object:
    """Call the GitHub issue API using the job-scoped token, without logging it."""
    request = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "uk-boundary-atlas refresh notification",
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return cast(object, json.load(response))


def upsert_issue(
    repository: str,
    run_id: str,
    title: str,
    body: str,
    request: Requester = github_request,
) -> str:
    """Create one issue per workflow run, updating it on reruns without reopening.

    Open and closed issues are paginated. Only notices created by the repository
    owner or GitHub Actions and containing this exact run marker are reused.
    """
    marker = f"<!-- uk-boundaries:catalogue-refresh:{run_id} -->"
    endpoint = f"/repos/{repository}/issues"
    page = 1
    while True:
        issues = request("GET", f"{endpoint}?state=all&per_page=100&page={page}", None)
        if not isinstance(issues, list):
            raise ValueError("Expected a GitHub issue list")
        for issue in issues:
            if (
                "pull_request" not in issue
                and marker in (issue.get("body") or "")
                and issue.get("user", {}).get("login")
                in {"github-actions[bot]", repository.split("/")[0]}
            ):
                if issue.get("title") != title or issue.get("body") != body:
                    request(
                        "PATCH", f"{endpoint}/{issue['number']}", dict(title=title, body=body)
                    )
                return str(issue["html_url"])
        if len(issues) < 100:
            break
        page += 1
    created = request("POST", endpoint, dict(title=title, body=body))
    if not isinstance(created, dict) or not isinstance(created.get("html_url"), str):
        raise ValueError("Expected a created GitHub issue URL")
    return str(created["html_url"])


def main() -> None:
    """Capture a compact job output or notify using trusted workflow context."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare", type=Path, help="Report to capture as a GitHub job output"
    )
    args = parser.parse_args()
    if args.prepare:
        payload = json.dumps(capture_report(args.prepare), separators=(",", ":"))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"report={payload}\n")
        return
    try:
        report = json.loads(os.environ.get("REFRESH_REPORT") or "{}")
    except ValueError:
        report = {}
    if not isinstance(report, dict):
        report = {}
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    title, body = build_notice(
        repository,
        run_id,
        os.environ["GITHUB_RUN_ATTEMPT"],
        os.environ["REFRESH_RESULT"],
        report,
        os.environ.get("REFRESH_ARTIFACT_ID", ""),
    )
    try:
        url = upsert_issue(repository, run_id, title, body)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"GitHub issue notification failed (HTTP {exc.code}). "
            "Check that issues are enabled and this job has issues: write permission."
        ) from None
    print(f"Catalogue refresh notice: {url}")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write(f"\n[Catalogue refresh issue]({url}) — @hulsiejames\n")


if __name__ == "__main__":
    main()
