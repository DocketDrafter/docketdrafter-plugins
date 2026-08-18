"""HTTP utilities.

Built on ``urllib3`` — the library ``requests`` itself is built on. It is pure
Python with no dependencies of its own, so one vendored tree works on every
platform, and it already provides connection pooling and a well-tested retry
policy including ``Retry-After`` support.

``requests`` is avoided only because it drags in ``charset_normalizer``, whose
published wheels contain compiled extensions; the plugin install path serves
files straight from the repository, so a compiled artifact would pin the plugin
to whichever machine built it.

This module is the single choke point for every network call, so retry and
rate-limit behaviour is configured once here for all callers.
"""

from __future__ import annotations

import json as jsonlib
from typing import Any

import urllib3
from urllib3.util.retry import Retry

USER_AGENT = "DocketDrafter-CourtListener-MCP/0.1 (+https://docketdrafter.com)"

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.5
MAX_BACKOFF_SECONDS = 30.0

# raise_on_status is off so an exhausted retry returns the final response and
# callers see the real status code rather than a MaxRetryError.
RETRY_POLICY = Retry(
    total=MAX_RETRIES,
    backoff_factor=BACKOFF_FACTOR,
    backoff_max=MAX_BACKOFF_SECONDS,
    status_forcelist=RETRY_STATUSES,
    allowed_methods=frozenset({"GET", "POST"}),
    respect_retry_after_header=True,
    raise_on_status=False,
    raise_on_redirect=False,
)


class HttpError(Exception):
    """A network or HTTP-status failure.

    The single exception callers catch, so no other module needs to know which
    transport is underneath.
    """

    def __init__(self, message: str, *, status_code: int | None = None, url: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


def _ca_certs() -> str | None:
    """Prefer certifi's CA bundle when available.

    Python installed from python.org on macOS does not read the system keychain,
    so platform defaults alone break HTTPS for users who never ran the bundled
    "Install Certificates" step. certifi is pure Python, so keeping it is free.
    """
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return None


_POOL: urllib3.PoolManager | None = None


def _pool() -> urllib3.PoolManager:
    """Return the shared pool, so connections are reused across calls."""
    global _POOL
    if _POOL is None:
        ca_certs = _ca_certs()
        _POOL = urllib3.PoolManager(
            retries=RETRY_POLICY,
            headers={"User-Agent": USER_AGENT},
            cert_reqs="CERT_REQUIRED",
            **({"ca_certs": ca_certs} if ca_certs else {}),
        )
    return _POOL


class Response:
    """The subset of the response surface this codebase uses."""

    __slots__ = ("status_code", "url", "content")

    def __init__(self, status_code: int, url: str, content: bytes):
        self.status_code = status_code
        self.url = url
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if not self.content:
            raise HttpError("Expected a JSON body but the response was empty", url=self.url)
        try:
            return jsonlib.loads(self.text)
        except jsonlib.JSONDecodeError as exc:
            raise HttpError(f"Response was not valid JSON: {exc}", url=self.url) from exc

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HttpError(
                f"HTTP {self.status_code} for {self.url}",
                status_code=self.status_code,
                url=self.url,
            )


def _request(
    method: str,
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None,
    fields: dict[str, Any] | None,
    raise_for_status: bool,
    retries: Any = None,
) -> Response:
    extra: dict[str, Any] = {}
    if method not in ("GET", "HEAD", "DELETE"):
        # Form-encode the body rather than multipart; CourtListener's
        # citation-lookup endpoint expects a urlencoded body. This keyword is
        # only accepted by the body-encoding path, not by GET.
        extra["encode_multipart"] = False

    try:
        raw = _pool().request(
            method,
            url,
            fields=fields or None,
            headers=headers,
            timeout=urllib3.Timeout(total=timeout),
            # None inherits the pool's standard policy; False disables retries
            # entirely for latency-bounded diagnostic calls.
            **({} if retries is None else {"retries": retries}),
            preload_content=True,
            **extra,
        )
    except urllib3.exceptions.HTTPError as exc:
        raise HttpError(f"Could not reach {url}: {exc}", url=url) from exc

    response = Response(raw.status, raw.geturl() or url, raw.data)
    if raise_for_status:
        response.raise_for_status()
    return response


def get(
    url: str,
    *,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
    params=None,
    raise_for_status: bool = True,
    retries: Any = None,
) -> Response:
    return _request(
        "GET",
        url,
        timeout=timeout,
        headers=headers,
        fields=params,
        raise_for_status=raise_for_status,
        retries=retries,
    )


def post(
    url: str,
    *,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
    data=None,
    raise_for_status: bool = True,
) -> Response:
    return _request(
        "POST",
        url,
        timeout=timeout,
        headers=headers,
        fields=data,
        raise_for_status=raise_for_status,
    )
