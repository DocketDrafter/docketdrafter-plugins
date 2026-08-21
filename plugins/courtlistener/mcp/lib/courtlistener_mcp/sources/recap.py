"""CourtListener RECAP docket fetch logic."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from courtlistener_mcp.config import (
    ensure_directory,
    get_data_dir,
    write_bytes_atomic,
    write_text_atomic,
)
from courtlistener_mcp.http import get
from courtlistener_mcp.sources.courtlistener import API_BASE_URL, auth_headers
from courtlistener_mcp.text import sanitize_filename

STORAGE_BASE_URL = "https://storage.courtlistener.com"
RECAP_STORAGE_RE = re.compile(r"/recap/gov\.uscourts\.([a-z0-9-]+)\.(\d+)/")
DOCKET_URL_RE = re.compile(r"/docket/(\d+)(?:/|$)")

# Dockets are the one mutable thing this system fetches: active cases grow new
# entries on a days-to-weeks cadence. Within that window the cache exists to
# make the get_docket -> download_docket_pdfs two-step pay for the entry walk
# once; beyond it, serving old entries is wrong, not thrifty.
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60

# CourtListener nests full extracted document text by default. Docket browsing
# needs metadata only; explicit field selection makes large-entry lookups much
# faster and keeps raw cache files small.
DOCKET_ENTRY_FIELDS = ",".join(
    (
        "id",
        "date_filed",
        "entry_number",
        "description",
        "recap_documents__id",
        "recap_documents__absolute_url",
        "recap_documents__document_number",
        "recap_documents__attachment_number",
        "recap_documents__description",
        "recap_documents__is_available",
        "recap_documents__filepath_local",
        "recap_documents__pacer_doc_id",
        "recap_documents__page_count",
    )
)
RECAP_DOCUMENT_FIELDS = ",".join(
    (
        "id",
        "docket_entry",
        "date_filed",
        "entry_number",
        "document_number",
        "attachment_number",
        "description",
        "is_available",
        "filepath_local",
        "pacer_doc_id",
        "page_count",
    )
)


def log(message: str) -> None:
    """Print a progress line immediately."""
    print(message, file=sys.stderr, flush=True)


def default_cache_dir(data_dir: Path | None = None) -> Path:
    """Return the cache directory for CourtListener RECAP API responses."""
    root = Path(data_dir).expanduser().resolve() if data_dir else get_data_dir()
    return root / "cache" / "courtlistener-api" / "recap"


_SWEPT_DIRS: set[Path] = set()


def _sweep_expired(cache_dir: Path) -> None:
    """Delete cache files past the TTL, once per directory per process.

    Anything older than the TTL can never be served again — reads reject it and
    a rewrite does not need it — so deletion is free of behaviour change. This
    keeps orphaned entries (cursor-keyed pages from walks never repeated) from
    accumulating forever.
    """
    if cache_dir in _SWEPT_DIRS:
        return
    _SWEPT_DIRS.add(cache_dir)
    if not cache_dir.is_dir():
        return
    cutoff = time.time() - DEFAULT_CACHE_TTL_SECONDS
    removed = 0
    for entry in cache_dir.glob("*.json"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue  # concurrent server or permissions; the file stays, harmlessly
    if removed:
        log(f"  cache swept {removed} expired file(s) from {cache_dir}")


def _cache_key(url: str, params: dict[str, Any] | None = None) -> str:
    query = urlencode(sorted((params or {}).items()), doseq=True)
    raw = f"{url}?{query}" if query else url
    return sha256(raw.encode("utf-8")).hexdigest()


def _cached_json_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    timeout: int = 90,
    max_age_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """GET JSON with a small persistent cache and timing logs.

    ``use_cache`` controls only whether a cached copy is *read*, and a cached
    copy older than ``max_age_seconds`` is treated as expired rather than
    served. A fresh response is always written back when a cache directory
    exists, so both a refresh and an expiry update the cache for the next call.
    """
    cache_path: Path | None = None
    if cache_dir is not None:
        ensure_directory(cache_dir)
        _sweep_expired(cache_dir)
        cache_path = cache_dir / f"{_cache_key(url, params)}.json"
        if use_cache and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age <= max_age_seconds:
                started = time.time()
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                log(f"  cache HIT {cache_path} (age {age/3600:.1f}h, {time.time() - started:.3f}s)")
                return data
            log(f"  cache EXPIRED {cache_path} (age {age/3600:.1f}h > {max_age_seconds/3600:.0f}h)")
        else:
            log(f"  cache {'MISS' if use_cache else 'BYPASS (refresh)'} {cache_path}")

    started = time.time()
    query = f"?{urlencode(sorted((params or {}).items()), doseq=True)}" if params else ""
    log(f"  api GET start {url}{query} (timeout={timeout}s)")
    response = get(url, timeout=timeout, headers=auth_headers(), params=params)
    elapsed = time.time() - started
    data = response.json()
    log(f"  api GET done {response.url} -> {response.status_code} ({elapsed:.3f}s)")
    if cache_path is not None:
        write_text_atomic(cache_path, json.dumps(data, indent=2, ensure_ascii=False))
        log(f"  cache WRITE {cache_path}")
    return data


@dataclass(frozen=True, slots=True)
class RecapDocumentRef:
    """Flattened document reference from a RECAP docket entry."""

    docket_id: int
    docket_entry_id: int | None
    entry_number: int | None
    entry_date: str
    entry_description: str
    document_id: int
    document_number: str
    attachment_number: int | None
    description: str
    pacer_doc_id: str
    is_available: bool
    filepath_local: str
    page_count: int | None

    @property
    def storage_url(self) -> str:
        return storage_url(self.filepath_local)

    @property
    def label(self) -> str:
        entry = self.entry_number if self.entry_number is not None else "?"
        doc = self.document_number or str(self.document_id)
        desc = self.description or self.entry_description or "No description"
        date = self.entry_date or "No date"
        return f"{date} | Entry {entry} | Doc {doc} | {desc}"


def storage_url(filepath_local: str) -> str:
    """Build the public CourtListener storage URL for a RECAP filepath."""
    if not filepath_local:
        return ""
    if filepath_local.startswith("http://") or filepath_local.startswith("https://"):
        return filepath_local
    return f"{STORAGE_BASE_URL}/{filepath_local.lstrip('/')}"


def fetch_docket(
    docket_id: int,
    *,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    timeout: int = 90,
) -> dict[str, Any]:
    """Fetch a CourtListener docket by ID."""
    return _cached_json_get(
        f"{API_BASE_URL}/dockets/{docket_id}/",
        cache_dir=cache_dir,
        use_cache=use_cache,
        timeout=timeout,
    )


def fetch_docket_by_pacer_case_id(
    court_id: str,
    pacer_case_id: str,
    *,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    timeout: int = 90,
) -> dict[str, Any]:
    """Fetch the unique CourtListener docket for a PACER court and case ID."""
    data = _cached_json_get(
        f"{API_BASE_URL}/dockets/",
        params={"court": court_id, "pacer_case_id": pacer_case_id},
        cache_dir=cache_dir,
        use_cache=use_cache,
        timeout=timeout,
    )
    results = data.get("results", [])
    if not results:
        raise ValueError(f"No docket found for court={court_id} pacer_case_id={pacer_case_id}")
    if len(results) > 1:
        ids = ", ".join(str(item.get("id")) for item in results[:10])
        raise ValueError(
            f"Found multiple dockets for court={court_id} pacer_case_id={pacer_case_id}: {ids}"
        )
    return results[0]


def parse_recap_storage_url(url: str) -> tuple[str, str]:
    """Extract CourtListener court ID and PACER case ID from a RECAP storage URL."""
    parsed = urlparse(url)
    match = RECAP_STORAGE_RE.search(parsed.path)
    if not match:
        raise ValueError(f"Could not parse RECAP storage URL: {url}")
    return match.group(1), match.group(2)


def parse_docket_url(url: str) -> int:
    """Extract a CourtListener docket ID from a public docket URL."""
    parsed = urlparse(url)
    match = DOCKET_URL_RE.search(parsed.path)
    if not match:
        raise ValueError(f"Could not extract docket ID from URL: {url}")
    return int(match.group(1))


def fetch_docket_entries_page(
    docket_id: int,
    *,
    next_url: str | None = None,
    page_size: int = 10,
    timeout: int = 90,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], int | None, str | None]:
    """Fetch one browseable page of docket entries.

    ``next_url`` must come from a prior CourtListener response and is validated
    by the MCP layer before it reaches this function.
    """
    url = next_url or f"{API_BASE_URL}/docket-entries/"
    params: dict[str, Any] | None = (
        None
        if next_url
        else {
            "docket": docket_id,
            "page_size": min(page_size, 25),
            "fields": DOCKET_ENTRY_FIELDS,
        }
    )
    data = _cached_json_get(
        url,
        timeout=timeout,
        params=params,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )
    results = (data.get("results") or [])[:page_size]
    count = data.get("count") if isinstance(data.get("count"), int) else None
    following = data.get("next") if isinstance(data.get("next"), str) else None
    log(f"  Browsed {len(results)} docket entries ({count if count is not None else '?'} total)")
    return results, count, following


def fetch_docket_entries(
    docket_id: int,
    *,
    timeout: int = 90,
    retries: int = 3,
    max_entries: int | None = None,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    entry_number: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch all docket entries for a CourtListener docket ID."""
    url = f"{API_BASE_URL}/docket-entries/"
    params: dict[str, Any] | None = {
        "docket": docket_id,
        "fields": DOCKET_ENTRY_FIELDS,
    }
    if entry_number is not None:
        params["entry_number"] = entry_number
    entries: list[dict[str, Any]] = []
    expected_count: int | None = None
    page = 1
    while url:
        log(f"Fetching docket entries page {page}...")
        for attempt in range(1, retries + 1):
            try:
                data = _cached_json_get(
                    url,
                    timeout=timeout,
                    params=params,
                    cache_dir=cache_dir,
                    use_cache=use_cache,
                )
                break
            except Exception:
                if attempt == retries:
                    raise
                delay = min(30, 2**attempt)
                log(
                    f"  Page {page} failed on attempt {attempt}/{retries}; "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
        if expected_count is None and isinstance(data.get("count"), int):
            expected_count = data["count"]
        results = data.get("results", [])
        entries.extend(results)
        if max_entries is not None and len(entries) >= max_entries:
            entries = entries[:max_entries]
        count_text = f"/{expected_count}" if expected_count is not None else ""
        log(f"  Found {len(results)} entries (total: {len(entries)}{count_text})")
        if max_entries is not None and len(entries) >= max_entries:
            log(f"  Reached --max-entries {max_entries}; stopping pagination.")
            break
        if expected_count is not None and len(entries) >= expected_count:
            break
        if entry_number is not None:
            break
        url = data.get("next")
        params = None
        page += 1
    return entries


def fetch_docket_entries_by_numbers(
    docket_id: int,
    entry_numbers: list[int],
    *,
    timeout: int = 90,
    retries: int = 3,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch docket entries by their visible PACER docket entry numbers."""
    entries: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for entry_number in entry_numbers:
        log(f"Fetching docket entry number {entry_number}...")
        found = fetch_docket_entries(
            docket_id,
            timeout=timeout,
            retries=retries,
            cache_dir=cache_dir,
            use_cache=use_cache,
            entry_number=entry_number,
        )
        if not found:
            log(f"  No docket entry found for entry_number={entry_number}")
        for entry in found:
            entry_id = entry.get("id")
            if isinstance(entry_id, int) and entry_id in seen_ids:
                continue
            if isinstance(entry_id, int):
                seen_ids.add(entry_id)
            entries.append(entry)
    return entries


def fetch_recap_documents_by_ids(
    docket_id: int,
    document_ids: list[int],
    *,
    timeout: int = 90,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch exact RECAP document records and verify docket ownership."""
    docs: list[dict[str, Any]] = []
    for document_id in document_ids:
        data = _cached_json_get(
            f"{API_BASE_URL}/recap-documents/{document_id}/",
            timeout=timeout,
            params={"fields": RECAP_DOCUMENT_FIELDS},
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        docket_value = data.get("docket")
        if docket_value is None:
            entry = data.get("docket_entry")
            if isinstance(entry, dict):
                docket_value = entry.get("docket")
        if isinstance(docket_value, str):
            try:
                docket_value = int(docket_value.rstrip("/").split("/")[-1])
            except ValueError:
                docket_value = None
        if docket_value not in (None, docket_id):
            raise ValueError(
                f"RECAP document {document_id} does not belong to docket {docket_id}"
            )
        docs.append(data)
    return docs


def fetch_recap_documents_by_numbers(
    docket_id: int,
    document_numbers: list[int],
    *,
    timeout: int = 90,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Fetch RECAP documents by visible PACER document numbers."""
    docs: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for document_number in document_numbers:
        log(f"Fetching RECAP document number {document_number}...")
        data = _cached_json_get(
            f"{API_BASE_URL}/recap-documents/",
            timeout=timeout,
            params={
                "docket_entry__docket": docket_id,
                "document_number": document_number,
                "fields": RECAP_DOCUMENT_FIELDS,
            },
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        results = data.get("results") or []
        log(f"  Found {len(results)} RECAP document(s)")
        for doc in results:
            doc_id = doc.get("id")
            if isinstance(doc_id, int) and doc_id in seen_ids:
                continue
            if isinstance(doc_id, int):
                seen_ids.add(doc_id)
            docs.append(doc)
    return docs


def _coerce_entry_number(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _document_number(document: dict[str, Any]) -> str:
    value = document.get("document_number")
    if value not in (None, ""):
        return str(value)
    value = document.get("document_type")
    if value not in (None, ""):
        return str(value)
    return str(document.get("id", ""))


def _entry_documents(entry: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("recap_documents", "documents"):
        value = entry.get(key)
        if isinstance(value, list):
            return value
    return []


def flatten_documents(docket_id: int, entries: list[dict[str, Any]]) -> list[RecapDocumentRef]:
    """Flatten nested RECAP documents from docket entries."""
    docs: list[RecapDocumentRef] = []
    for entry in entries:
        entry_number = _coerce_entry_number(entry.get("entry_number"))
        entry_date = entry.get("date_filed") or entry.get("date_created") or ""
        entry_description = entry.get("description") or ""
        docket_entry_id = entry.get("id")
        for document in _entry_documents(entry):
            document_id = document.get("id")
            if document_id is None:
                continue
            docs.append(
                RecapDocumentRef(
                    docket_id=docket_id,
                    docket_entry_id=docket_entry_id,
                    entry_number=entry_number,
                    entry_date=entry_date,
                    entry_description=entry_description,
                    document_id=int(document_id),
                    document_number=_document_number(document),
                    attachment_number=document.get("attachment_number"),
                    description=document.get("description") or document.get("short_description") or "",
                    pacer_doc_id=str(document.get("pacer_doc_id") or ""),
                    is_available=bool(document.get("is_available")),
                    filepath_local=document.get("filepath_local") or "",
                    page_count=document.get("page_count"),
                )
            )
    return docs


def flatten_recap_documents(docket_id: int, documents: list[dict[str, Any]]) -> list[RecapDocumentRef]:
    """Flatten direct recap-document endpoint results into document refs."""
    docs: list[RecapDocumentRef] = []
    for document in documents:
        document_id = document.get("id")
        if document_id is None:
            continue
        docket_entry = document.get("docket_entry")
        docket_entry_id: int | None = None
        if isinstance(docket_entry, str):
            try:
                docket_entry_id = int(docket_entry.rstrip("/").split("/")[-1])
            except ValueError:
                docket_entry_id = None
        docs.append(
            RecapDocumentRef(
                docket_id=docket_id,
                docket_entry_id=docket_entry_id,
                entry_number=_coerce_entry_number(document.get("entry_number")),
                entry_date=document.get("date_filed") or document.get("entry_date_filed") or "",
                entry_description=document.get("description") or "",
                document_id=int(document_id),
                document_number=_document_number(document),
                attachment_number=document.get("attachment_number"),
                description=document.get("description") or document.get("short_description") or "",
                pacer_doc_id=str(document.get("pacer_doc_id") or ""),
                is_available=bool(document.get("is_available")),
                filepath_local=document.get("filepath_local") or "",
                page_count=document.get("page_count"),
            )
        )
    return docs


def docket_output_dir(docket: dict[str, Any], *, data_dir: Path | None = None) -> Path:
    """Return the local output directory for a docket."""
    root = Path(data_dir).expanduser().resolve() if data_dir else get_data_dir()
    court_id = docket.get("court_id") or "unknown-court"
    docket_id = docket.get("id")
    slug = docket.get("slug") or sanitize_filename(docket.get("case_name") or "docket")
    safe_slug = sanitize_filename(str(slug)).lower()
    dirname = f"{docket_id}-{safe_slug}" if docket_id else safe_slug
    return root / "dockets" / "courtlistener" / str(court_id) / dirname


def pdf_filename(doc: RecapDocumentRef) -> str:
    """Return a stable PDF filename for a flattened RECAP document."""
    entry = f"{doc.entry_number:04d}" if doc.entry_number is not None else "unknown"
    attachment = f"-att-{doc.attachment_number}" if doc.attachment_number is not None else ""
    stem = f"entry-{entry}-doc-{doc.document_number}{attachment}-recap-{doc.document_id}"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return f"{stem}.pdf"


def write_json(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def write_manifest(
    path: Path,
    *,
    docket: dict[str, Any],
    docs: list[RecapDocumentRef],
    pdf_paths: dict[int, Path] | None = None,
) -> None:
    """Write a human-readable manifest for a fetched docket."""
    pdf_paths = pdf_paths or {}
    lines = [
        f"# {docket.get('case_name') or 'CourtListener Docket'}",
        "",
        f"- Docket ID: {docket.get('id', '')}",
        f"- Court: {docket.get('court_id', '')}",
        f"- Docket Number: {docket.get('docket_number', '')}",
        f"- Date Filed: {docket.get('date_filed', '')}",
        f"- Last Filing: {docket.get('date_last_filing', '')}",
        "",
        "## Documents",
        "",
    ]
    for doc in docs:
        entry = doc.entry_number if doc.entry_number is not None else "?"
        available = "yes" if doc.is_available and doc.filepath_local else "no"
        lines.extend(
            [
                f"### {doc.entry_date or 'No date'} - Entry {entry} - Doc {doc.document_number}",
                "",
                f"- Description: {doc.description or doc.entry_description}",
                f"- Entry Description: {doc.entry_description}",
                f"- RECAP Document ID: {doc.document_id}",
                f"- PACER Doc ID: {doc.pacer_doc_id}",
                f"- Available: {available}",
                f"- Source URL: {doc.storage_url}",
            ]
        )
        if doc.document_id in pdf_paths:
            lines.append(f"- PDF: {pdf_paths[doc.document_id]}")
        lines.append("")
    write_text_atomic(path, "\n".join(lines).rstrip() + "\n")


def download_document(doc: RecapDocumentRef, pdf_dir: Path, *, overwrite: bool = False) -> Path | None:
    """Download one available RECAP document PDF."""
    if not doc.is_available or not doc.filepath_local:
        log(f"  skip unavailable document {doc.document_id} ({doc.label})")
        return None
    ensure_directory(pdf_dir)
    output_path = pdf_dir / pdf_filename(doc)
    if output_path.exists() and not overwrite:
        log(f"  pdf exists {output_path}")
        return output_path
    log(f"  pdf GET start {doc.storage_url}")
    started = time.time()
    response = get(doc.storage_url, timeout=120)
    write_bytes_atomic(output_path, response.content)
    log(f"  pdf WRITE {output_path} ({len(response.content)} bytes, {time.time() - started:.3f}s)")
    return output_path
