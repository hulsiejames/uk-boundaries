"""Shared types at the publisher JSON and HTTP boundaries.

Publisher fields and audited overrides are extensible JSON objects, so their
values remain dynamic. Function arguments, results and HTTP operations are typed
without restricting or rewriting those external schemas.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from email.message import Message
from typing import Any, Protocol, TypeAlias
from urllib.request import Request

JsonObject: TypeAlias = dict[str, Any]
UrlChecker: TypeAlias = Callable[[str], JsonObject]


class UrlResponse(Protocol):
    """Expose the response metadata needed for a bounded link check."""

    @property
    def headers(self) -> Message | Mapping[str, str]:
        """Return publisher response headers."""
        ...

    @property
    def status(self) -> int:
        """Return the HTTP response status code."""
        ...

    def geturl(self) -> str:
        """Return the final URL after any redirects."""
        ...

    def read(self, size: int) -> bytes:
        """Read at most the requested number of response bytes."""
        ...


# A callable protocol describes one operation rather than a concrete service class.
class UrlOpener(Protocol):  # pylint: disable=too-few-public-methods
    """Open a metadata request with an explicit timeout."""

    def __call__(
        self, request: Request, *, timeout: int
    ) -> AbstractContextManager[UrlResponse]:
        """Return a context manager that closes the response after checking."""
        ...
