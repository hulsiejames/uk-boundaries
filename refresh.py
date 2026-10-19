"""Refresh the catalogue and check links without downloading GIS files.

Default: write a reviewable candidate under work/refresh. --apply stages validated
metadata in dist; it does not commit, merge or publish anything.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from dataset_metadata import apply_metadata, refresh_metadata, write_metadata
from ingest import ROOT, build, fetch_ons, write_catalogue
from metadata_types import JsonObject, UrlChecker, UrlOpener

# HTTPS responses implement the narrow protocol used here; urllib's stubs are wider.
_default_url_opener: UrlOpener = cast(UrlOpener, urllib.request.urlopen)

BROKEN = {"missing", "invalid"}
ATTENTION = BROKEN | {"restricted", "inconclusive"}
SEMANTIC = [
    "title",
    "levels",
    "kind",
    "vintage",
    "years",
    "countries",
    "variant",
    "provider",
    "type",
    "formats",
    "source",
    "downloads",
    "service",
    "method",
    "dates",
    "areas",
    "centroidWeight",
    "centroidWeightBasis",
]


def now() -> str:
    """Return the check timestamp in UTC, retaining second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def http_state(code: int) -> str:
    """Distinguish missing and restricted responses from temporary failures."""
    if code in (404, 410):
        return "missing"
    if code in (401, 403):
        return "restricted"
    return "inconclusive"


def check_url(url: str, opener: UrlOpener = _default_url_opener) -> JsonObject:
    """Check a public HTTPS URL without saving GIS file bodies.

    Parameters
    ----------
    url : str
        Public source, file or service URL; embedded credentials are rejected.
    opener : callable
        Request opener, injectable for offline checks. HEAD is attempted first;
        fallback GET requests a bounded range and reads at most 512 JSON bytes.

    Returns
    -------
    dict
        Reachability state and response metadata. Redirect query strings are
        removed from the report; HTTP 200 JSON errors remain failures.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return dict(state="invalid", detail="Expected a public HTTPS URL")
    last: JsonObject | None = None
    for method in ("HEAD", "GET"):
        headers = {"User-Agent": "UK-Boundary-Atlas link check"}
        if method == "GET":
            headers["Range"] = "bytes=0-511"
        try:
            with opener(
                urllib.request.Request(url, headers=headers, method=method), timeout=15
            ) as response:
                final = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                if method == "HEAD" and "json" in content_type.lower():
                    continue
                if method == "GET" and "json" in content_type.lower():
                    prefix = response.read(512).decode("utf-8", errors="replace").lstrip()
                    if re.match(r'\{\s*"error"\s*:', prefix):
                        code_match = re.search(r'"code"\s*:\s*(\d+)', prefix)
                        code = int(code_match.group(1)) if code_match else 0
                        return dict(
                            state=http_state(code),
                            code=code,
                            detail="Publisher returned a JSON error",
                        )
                # Do not persist temporary signed redirect query strings.
                final_public = urllib.parse.urlunsplit(
                    (*urllib.parse.urlsplit(final)[:3], "", "")
                )
                if urllib.parse.urlsplit(final).scheme != "https":
                    return dict(
                        state="inconclusive",
                        code=response.status,
                        detail="Publisher redirects to non-HTTPS",
                        finalUrl=final_public,
                    )
                return dict(
                    state="reachable",
                    code=response.status,
                    finalUrl=final_public,
                    redirected=final != url,
                    contentType=content_type,
                    method=method,
                )
        except urllib.error.HTTPError as exc:
            last = dict(state=http_state(exc.code), code=exc.code, detail=str(exc.reason))
            exc.close()
        # Network and malformed-response failures remain inconclusive, not missing.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            last = dict(state="inconclusive", detail=str(exc))
    assert last is not None  # A successful request returns before this point.
    return last


def preserve_history(old: JsonObject, candidate: JsonObject) -> list[str]:
    """Retain historical ONS records missing from current publisher discovery.

    Parameters
    ----------
    old : dict
        Previously published catalogue, which remains unmodified.
    candidate : dict
        New catalogue to update in place with explicit listing-status flags.

    Returns
    -------
    list of str
        Missing ONS record IDs. Their vintages and original check dates are kept.
    """
    old_rows = {r["id"]: r for r in old["items"]}
    ids = {r["id"] for r in candidate["items"]}
    missing = sorted(key for key in old_rows if key.startswith("ons:") and key not in ids)
    for row in candidate["items"]:
        if row["provider"] == "ons":
            row["sourceListing"] = "present"
    for key in missing:
        row = copy.deepcopy(old_rows[key])
        row["sourceListing"] = "not-found"
        candidate["items"].append(row)
    candidate["items"].sort(
        key=lambda r: (-max(r["years"], default=0), r["title"].casefold(), r["id"])
    )
    return missing


def validate_candidate(
    old: JsonObject, candidate: JsonObject, metadata: JsonObject, missing: list[str]
) -> list[str]:
    """Reject duplicate IDs, mismatched schemas and widespread new capture failures.

    Parameters
    ----------
    old : dict
        Published catalogue used to distinguish new losses from reviewed gaps.
    candidate : dict
        Proposed catalogue, including retained historical records.
    metadata : dict
        Proposed service metadata cache, keyed by catalogue record ID.
    missing : list of str
        ONS records absent from the fresh listing.

    Returns
    -------
    list of str
        Rejection reasons. An empty list means the candidate can be reviewed.
    """
    errors = []
    ids = [r["id"] for r in candidate["items"]]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate record IDs")
    active_ons = {
        r["id"]
        for r in old["items"]
        if r["provider"] == "ons" and r.get("sourceListing") != "not-found"
    }
    if len(set(missing) & active_ons) > max(10, len(active_ons) * 0.05):
        errors.append(
            "More than 5% of ONS records disappeared from the scan; review before applying"
        )
    entries = list(metadata["records"].values())
    failed = sum(
        r["status"] == "unavailable" or bool(r.get("lastAttemptErrors")) for r in entries
    )
    if entries and failed > max(10, len(entries) * 0.10):
        errors.append(
            "More than 10% of service metadata captures failed; retaining the "
            "published snapshot"
        )
    levels = {layer["id"] for layer in candidate["levels"]}
    providers = {p["id"] for p in candidate["providers"]}
    for row in candidate["items"]:
        if not set(row["levels"]) <= levels or row["provider"] not in providers:
            errors.append("Unknown taxonomy for " + row["id"])
        if "geometry" in row or "features" in row:
            errors.append("Unexpected feature data in " + row["id"])
        if row.get("attributes"):
            entry = metadata["records"].get(row["id"])
            if not entry or entry["service"] != row["service"]:
                errors.append("Schema association mismatch for " + row["id"])
    return errors


def check_links(
    candidate: JsonObject, metadata: JsonObject, checker: UrlChecker = check_url
) -> dict[str, JsonObject]:
    """Check distinct links and attach record health without rewriting source URLs.

    Parameters
    ----------
    candidate : dict
        Catalogue updated in place with health flags and temporary per-link data.
    metadata : dict
        Captured service definitions, used to distinguish access/capture failures.
    checker : callable
        URL checker, injectable for offline verification.

    Returns
    -------
    dict
        Per-URL check results with source/download/service roles. ONS existence
        comes from publisher discovery, not HTTP-200 portal shells.
    """
    # ONS existence comes from the fresh official item search. HTTP-200 SPA landing
    # pages cannot establish dataset existence. Check curated pages and all files.
    roles: dict[str, set[str]] = {}
    for row in candidate["items"]:
        if row["provider"] != "ons":
            roles.setdefault(row["source"], set()).add("source")
        for file in row["downloads"]:
            roles.setdefault(file["url"], set()).add("download")
        if row.get("service") and not re.fullmatch(
            r"https://[^?#]+/(FeatureServer|MapServer)(/\d+)?/?", row["service"], re.I
        ):
            roles.setdefault(row["service"], set()).add("service")
    results = {}
    urls = sorted(roles)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for index, (url, result) in enumerate(
            zip(urls, pool.map(checker, urls), strict=False), 1
        ):
            results[url] = dict(result, roles=sorted(roles[url]))
            if index % 100 == 0 or index == len(urls):
                print(f"Checked links: {index}/{len(urls)}", flush=True)
    for row in candidate["items"]:
        checks = []
        if row["provider"] != "ons":
            checks.append(dict(url=row["source"], role="source", **results[row["source"]]))
        for file in row["downloads"]:
            result = results[file["url"]]
            if (
                result["state"] == "reachable"
                and "html" in result.get("contentType", "").lower()
            ):
                result = dict(
                    result,
                    state="inconclusive",
                    detail="File link responded with HTML; inspect the publisher",
                )
                results[file["url"]] = result
            checks.append(dict(url=file["url"], role="download", **result))
        service = row.get("service")
        entry = metadata["records"].get(row["id"])
        if service in results:
            checks.append(dict(url=service, role="service", **results[service]))
        elif entry and entry["service"] == service:
            failures = entry.get("lastAttemptErrors") or entry.get("errors") or []
            state = (
                "restricted"
                if any("403" in e or "permissions" in e.lower() for e in failures)
                else "inconclusive"
                if failures
                else "metadata-reachable"
            )
            checks.append(
                dict(
                    url=service,
                    role="service",
                    state=state,
                    detail="; ".join(failures),
                    checked=entry.get("lastAttempt") or entry["checked"],
                )
            )
        issues = [c for c in checks if c["state"] in ATTENTION]
        row["linkHealth"] = dict(
            checked=candidate["checked"],
            state="attention"
            if issues or row.get("sourceListing") == "not-found"
            else "checked",
            issues=len(issues),
        )
        files = [c for c in checks if c["role"] == "download"]
        if files:
            row["linkHealth"]["downloadState"] = (
                "reachable"
                if any(c["state"] == "reachable" for c in files)
                else "missing"
                if all(c["state"] == "missing" for c in files)
                else "unconfirmed"
            )
        # Preserve per-link states in the separate report, loaded only on request.
        row["linkHealth"]["reportKey"] = row["id"]
        row["_linkChecks"] = checks
    return results


def changes(old: JsonObject, candidate: JsonObject) -> dict[str, list[str]]:
    """List new and semantically changed records, excluding check-date churn."""
    before = {r["id"]: r for r in old["items"]}
    after = {r["id"]: r for r in candidate["items"]}
    return dict(
        added=sorted(after.keys() - before.keys()),
        changed=sorted(
            key
            for key in before.keys() & after.keys()
            if any(before[key].get(f) != after[key].get(f) for f in SEMANTIC)
        ),
    )


def schema_changes(before: JsonObject, after: JsonObject) -> list[str]:
    """Compare fields, CRS, download flags and counts while ignoring check dates."""

    def schema(entry: JsonObject) -> list[JsonObject]:
        """Select the layer properties relevant to a schema-change report."""
        return [
            dict(
                id=layer["id"],
                fields=layer["fields"],
                spatialReference=layer.get("spatialReference"),
                downloadable=layer.get("downloadable"),
                recordCount=layer.get("recordCount"),
            )
            for layer in entry.get("layers", [])
        ]

    return sorted(
        key
        for key in before["records"].keys() & after["records"].keys()
        if schema(before["records"][key]) != schema(after["records"][key])
    )


def report_markdown(report: JsonObject) -> str:
    """Summarise a check for the Actions run and its review PR."""
    s = report["summary"]
    return (
        f"Refresh checked {report['finished']}.\n\n"
        f"- {s['records']} source records; {s['added']} added, "
        f"{s['changed']} listing/date changes.\n"
        f"- {s['schemaChanged']} changed layer schemas, record counts or download flags.\n"
        f"- {s['notListed']} historical ONS records absent from the current listing, "
        "retained for review.\n"
        f"- {s['httpLinks']} distinct HTTP links checked; {s['missingLinks']} missing, "
        f"{s['restrictedLinks']} restricted, {s['inconclusiveLinks']} inconclusive.\n"
        f"- {s['metadataServices']} ArcGIS service metadata checks; "
        f"{s['serviceIssues']} have capture or access issues.\n"
        f"- {s['attentionRecords']} records need attention. "
        "HTTP reachability does not certify file contents or licences.\n\n"
        "Publisher metadata and link checks contain no polygons. Curated sources are "
        "checked for reachability, not automatically rediscovered. Redirects are "
        "reported without silently rewriting historical URLs. Inspect "
        "`dist/refresh-status.json` for per-link results.\n\n"
        "The refresh workflow saves a tested candidate as an artifact. Review and "
        "commit its three JSON files, then merge the changes to update GitHub Pages.\n"
    )


def main() -> None:
    """Run the refresh CLI, applying only a validated metadata candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "refresh")
    parser.add_argument("--ons-cache", type=Path)
    parser.add_argument("--ons-checked", help="Original scan date, required with --ons-cache")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Stage the validated candidate in dist (no commit or deployment)",
    )
    args = parser.parse_args()
    if args.ons_cache and not args.ons_checked:
        parser.error("--ons-cache requires --ons-checked")
    started = now()
    old = json.loads((ROOT / "dist/catalogue.json").read_text(encoding="utf-8"))
    previous = json.loads((ROOT / "dist/dataset-metadata.json").read_text(encoding="utf-8"))
    raw = (
        json.loads(args.ons_cache.read_text(encoding="utf-8"))
        if args.ons_cache
        else fetch_ons()
    )
    candidate = build(raw, ons_checked=args.ons_checked if args.ons_cache else None)
    missing = preserve_history(old, candidate)
    metadata = refresh_metadata(candidate["items"], previous)
    for row in candidate["items"]:
        apply_metadata(row, metadata["records"].get(row["id"]))
    candidate["sourceAudit"]["publisherMetadataChecked"] = metadata["checked"]
    links = check_links(candidate, metadata)
    errors = validate_candidate(old, candidate, metadata, missing)
    delta = changes(old, candidate)
    delta["schemaChanged"] = schema_changes(previous, metadata)
    states = Counter(v["state"] for v in links.values())
    report = dict(
        schemaVersion=1,
        status="rejected" if errors else "checked",
        started=started,
        finished=now(),
        errors=errors,
        summary=dict(
            records=len(candidate["items"]),
            added=len(delta["added"]),
            changed=len(delta["changed"]),
            schemaChanged=len(delta["schemaChanged"]),
            notListed=len(missing),
            httpLinks=len(links),
            missingLinks=states["missing"],
            restrictedLinks=states["restricted"],
            inconclusiveLinks=states["inconclusive"],
            metadataServices=len(metadata["records"]),
            serviceIssues=sum(
                bool(v["errors"] or v.get("lastAttemptErrors"))
                for v in metadata["records"].values()
            ),
            attentionRecords=sum(
                r["linkHealth"]["state"] == "attention" for r in candidate["items"]
            ),
        ),
        changes=delta,
        notListed=missing,
        links=links,
        records={
            r["id"]: dict(
                title=r["title"],
                sourceListing=r.get("sourceListing"),
                checks=r.pop("_linkChecks"),
            )
            for r in candidate["items"]
        },
    )
    candidate["sourceAudit"]["refresh"] = dict(
        status=report["status"], finished=report["finished"], summary=report["summary"]
    )
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    write_catalogue(candidate, out / "catalogue.json")
    write_metadata(metadata, out / "dataset-metadata.json")
    (out / "refresh-status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (out / "summary.md").write_text(report_markdown(report), encoding="utf-8", newline="\n")
    print(report_markdown(report), flush=True)
    if errors:
        raise SystemExit(
            "Refresh rejected; dist has not been changed. See the candidate report."
        )
    if args.apply:
        for file in ("catalogue.json", "dataset-metadata.json", "refresh-status.json"):
            shutil.copyfile(out / file, ROOT / "dist" / file)


if __name__ == "__main__":
    main()
