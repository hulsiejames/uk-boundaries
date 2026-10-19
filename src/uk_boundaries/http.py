"""Bound public metadata reads and close streamed publisher responses."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from email.message import Message
from typing import Protocol, cast

from .models import BoundaryError, JsonObject


class Response(Protocol):
    """Expose the operations required for bounded metadata and streamed files."""

    @property
    def headers(self) -> Message | Mapping[str, str]:
        """Return the publisher's response headers."""
        ...

    @property
    def status(self) -> int:
        """Return the HTTP status code."""
        ...

    def geturl(self) -> str:
        """Return the final response URL."""
        ...

    def read(self, amount: int) -> bytes:
        """Read at most amount bytes from the response."""
        ...

    def close(self) -> None:
        """Close the publisher response and its connection."""
        ...


def validate_url(url: str) -> str:
    """Require HTTPS and reject embedded username/password credentials."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise BoundaryError("Publisher URLs must use HTTPS without embedded credentials")
    return url


def public_url(url: str) -> str:
    """Omit temporary redirect tokens from persisted provenance."""
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.urlencode(
        [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.query)
            if key.casefold() in {"id", "layers", "f", "format"}
        ]
    )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


@contextmanager
def open_url(url: str, *, timeout: float) -> Iterator[Response]:
    """Open a public publisher request and close it after use."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request = urllib.request.Request(
        validate_url(url), headers={"User-Agent": "UK-Boundary-Atlas Python API/0.1"}
    )
    response = cast(Response, urllib.request.urlopen(request, timeout=timeout))
    try:
        validate_url(response.geturl())
        yield response
    finally:
        response.close()


def read_json(url: str, *, timeout: float) -> JsonObject:
    """Read a JSON object with a 32 MiB bound and explicit ArcGIS error handling."""
    try:
        with open_url(url, timeout=timeout) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise BoundaryError("Publisher metadata exceeds the 32 MiB limit")
        data = json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise BoundaryError(f"Could not read publisher metadata: {public_url(url)}") from exc
    if not isinstance(data, dict) or "error" in data:
        raise BoundaryError(f"Publisher did not return usable metadata: {public_url(url)}")
    return data
