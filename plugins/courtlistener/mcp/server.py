#!/usr/bin/env python3
"""CourtListener MCP server (stdio).

Exposes the ``courtlistener_mcp`` package, which holds all CourtListener and
RECAP logic, as MCP tools. The JSON-RPC layer is hand-rolled against the stdlib
rather than the ``mcp`` SDK: that SDK depends on ``pydantic-core``, which ships
compiled per-platform wheels and cannot be vendored portably. For the same
reason HTTP goes through ``courtlistener_mcp.http`` on ``urllib`` rather than
``requests``. Runtime dependencies are declared in ``pyproject.toml`` and
managed by the MCPB host's UV runtime.

The API key is read from the ``COURTLISTENER_API_KEY`` environment variable by
``courtlistener_mcp.config``. Claude injects it from the OS keychain, so the
key never appears in conversation, in a command line, or in a plaintext file.
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

MINIMUM_PYTHON = (3, 10)

SERVER_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SERVER_DIR / "vendor"

# Set when no interpreter new enough could be found. The server still speaks the
# protocol in that state so the user sees an explanation inside Claude rather
# than a server that silently fails to appear.
PYTHON_TOO_OLD = ""

# Set when runtime dependencies could not be imported. Same contract as
# PYTHON_TOO_OLD: answer the protocol, explain the problem through the tools.
DEPENDENCIES_MISSING = ""

# Every third-party module the server actually needs at runtime. Declared once so
# the startup probe and check_setup cannot drift apart: when `requests` was
# replaced by `urllib3`, a probe that only checked `bs4` reported "Dependencies:
# OK" while every network call was about to fail.
REQUIRED_MODULES = ("bs4", "urllib3")


def _find_modern_python() -> str | None:
    """Locate a Python new enough to run this server.

    A GUI-launched app does not inherit the user's shell PATH, so bare
    ``python3`` can resolve to the macOS system interpreter (3.9), which cannot
    parse the modern union syntax used by this server's dependencies.
    """
    candidates = [
        "python3.14",
        "python3.13",
        "python3.12",
        "python3.11",
        "python3.10",
    ]
    searched = [shutil.which(name) for name in candidates]
    searched += [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        str(Path.home() / ".pyenv" / "shims" / "python3"),
    ]
    for candidate in searched:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode != 0:
            continue
        try:
            major, minor = (int(part) for part in probe.stdout.strip().split("."))
        except ValueError:
            continue
        if (major, minor) >= MINIMUM_PYTHON:
            return candidate
    return None


if sys.version_info < MINIMUM_PYTHON:
    _running = f"{sys.version_info[0]}.{sys.version_info[1]}"
    _replacement = _find_modern_python()
    if _replacement:
        print(
            f"[courtlistener-mcp] python {_running} is too old; "
            f"re-executing with {_replacement}",
            file=sys.stderr,
            flush=True,
        )
        try:
            os.execv(
                _replacement, [_replacement, str(Path(__file__).resolve()), *sys.argv[1:]]
            )
        except OSError as _exc:  # fall through to the explanation below
            print(
                f"[courtlistener-mcp] re-exec failed: {_exc}",
                file=sys.stderr,
                flush=True,
            )
    PYTHON_TOO_OLD = (
        f"CourtListener needs Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer, "
        f"but Claude started it with Python {_running} and no newer version was found "
        "on this computer.\n\n"
        "Install Python from https://www.python.org/downloads/ (the standard "
        "installer is fine), then quit and reopen Claude."
    )


def _scrub_unresolved_templates() -> None:
    """Drop env vars still holding unresolved ${...} config placeholders.

    If a client launches the server without substituting ${user_config.*}
    references, the literal template string arrives as the value. Treating it
    as real would report a bogus API key as "found" and create a directory
    literally named "${user_config.library_dir}".
    """
    for name in ("COURTLISTENER_API_KEY", "COURTLISTENER_DATA_DIR"):
        value = os.environ.get(name, "")
        if value.startswith("${") and value.endswith("}"):
            log(f"{name} arrived as unresolved template {value!r}; treating as unset")
            del os.environ[name]


def _resolve_lib_dir() -> Path:
    """Locate the ``courtlistener_mcp`` implementation package.

    Two layouts are supported: the repo layout, where the package sits in
    ``mcp/lib``, and the flat .mcpb bundle layout, where it is copied next to
    this file.
    """
    repo_layout = SERVER_DIR / "lib"
    if (repo_layout / "courtlistener_mcp").is_dir():
        return repo_layout
    return SERVER_DIR


LIB_DIR = _resolve_lib_dir()

# Guidance that cannot live in a tool description, because it governs what
# Claude concludes and writes *after* a tool returns — or when no tool runs at
# all. Per-call mechanics stay in the individual tool descriptions.
SERVER_INSTRUCTIONS = """\
CourtListener provides American court opinions and PACER filings from the Free
Law Project. Material retrieved through these tools is saved to a persistent
research library on the user's computer.

Validity of authority. CourtListener does NOT provide a Shepard's- or
KeyCite-style validity signal. Nothing these tools return establishes whether a
case is still good law. To assess later treatment, find opinions that cite the
target, retrieve them, and read how each one treats it — a citing reference
alone does not show whether it follows, distinguishes, limits, or criticizes.
Never state or imply that a case is still valid authority on the strength of a
search result.

Reading before characterization. Search results provide metadata only. NEVER
state or imply what an opinion holds, why it matters, whether it supports a
proposition, or how it applies a legal test unless you have first retrieved that
opinion with get_opinions and read its text. Do not substitute model memory for
reading the retrieved opinion. You may report search-result metadata such as
case name, citation, court, date, and publication status, but clearly distinguish
that metadata from a verified description of the opinion.

Court identifiers. Always resolve a court ID with search_courts
before filtering by court, even when the ID looks obvious. A state abbreviation
does not mean every court in that state: 'ny' is valid but means only the New
York Court of Appeals.

Citing opinions. Whenever you refer to a CourtListener opinion in a response,
hyperlink the case name or citation to its CourtListener URL. This applies to
search results, recommendations, summaries, comparisons, and opinions already in
the library. Do not present an unlinked list of cases when URLs are available.

Reporting retrieval honestly. get_opinions returns a status. Report
'already_saved' as already in the user's library, not as a new download.

Docket entries. NEVER guess or infer a docket entry number or document number.
In particular, NEVER assume that a complaint is entry 1 merely because
complaints are often filed first. Before EVERY download, you MUST inspect the
actual docket with get_docket and identify the requested filing from the entry
description and document metadata returned by CourtListener. For ANY request
for a specific filing, regardless of docket size, search RECAP first with
`docket_id` plus `short_description` terms, then confirm the selected entry with
a targeted get_docket call. get_docket's untargeted mode is for docket overviews,
nearby procedural context, or fallback when filing search is unsuccessful; it
returns 10 entries in CourtListener's native order by default (hard maximum 25)
and has no sort option. Browse another range with next_cursor only when that
context is actually needed. Only skip a new lookup when an earlier get_docket
result in this conversation already identified the exact filing and supplied
its entry or document number. Search RECAP filing metadata
freely before downloading: a docket_id plus description query can locate a
filing without downloading PDFs. Prefer exact recap_document_ids. Selecting an
entry or visible document number downloads only its main document by default;
attachments require explicit recap_document_ids or include_attachments=true.
Use the same search-first workflow for every docket: search RECAP with docket_id
plus short_description terms (for example, short_description:(complaint)), then
confirm the targeted entry with get_docket. Do not browse docket pages merely to
locate a specific filing. RECAP search returns matching filing records nested
under each docket and may report that more matches exist.

Library hygiene. The library folder is for material downloaded from
CourtListener only. Never write research memos, briefs, drafts, DOCX or PDF
deliverables, spreadsheets, or working scripts into it, and never use it as a
working, scratch, or output directory. Create deliverables in your normal output
location instead.

Search documentation. Before the first call to search_opinions, search_recap,
or download_search_results in each conversation, call read_search_docs and read
its complete output. This is required even for a simple query. Once it has been
read in the current conversation, use it for later searches without calling it
again. Construct every query according to the guide.

Searching thoroughly. Before reporting that CourtListener has nothing, try
reasonable variations of vocabulary, party name, court, date range, docket
number, and citation format.
"""

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
SERVER_NAME = "courtlistener"
SERVER_VERSION = "0.0.7"




def log(message: str) -> None:
    """Write a diagnostic line to stderr.

    stdout carries the JSON-RPC stream and must never receive anything else.
    """
    print(f"[courtlistener-mcp] {message}", file=sys.stderr, flush=True)


def _missing_modules() -> list[str]:
    """Return the names of REQUIRED_MODULES that cannot be imported."""
    missing = []
    for name in REQUIRED_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def _ensure_dependencies() -> None:
    """Put legacy vendored dependencies on the path, then verify imports.

    In an installed MCPB, the host's UV runtime installs the dependencies
    declared in pyproject.toml before launching this process. VENDOR_DIR remains
    supported only for compatibility with older bundles.
    """
    global DEPENDENCIES_MISSING

    if PYTHON_TOO_OLD:
        return
    if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))
    importlib.invalidate_caches()
    missing = _missing_modules()
    if missing:
        DEPENDENCIES_MISSING = (
            "CourtListener could not load required Python "
            f"package(s): {', '.join(missing)}.\n\n"
            "The connector's UV runtime normally installs these automatically, so this "
            "usually means setup was interrupted. Reinstall the CourtListener "
            "extension, then quit and reopen Claude.\n\n"
            f"Expected them in: {VENDOR_DIR}"
        )
        log(DEPENDENCIES_MISSING.replace("\n\n", " "))


_ensure_dependencies()

if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))


def _library_dir() -> Path | None:
    """Return the configured library directory, if any.

    Extension config can arrive with ``${HOME}``/``$HOME`` still literal, so
    expand those before touching the filesystem — otherwise a directory named
    ``${HOME}`` gets created in the process's working directory.
    """
    configured = os.getenv("COURTLISTENER_DATA_DIR")
    if not configured:
        return None
    home = str(Path.home())
    for token in ("${HOME}", "$HOME", "~"):
        if configured.startswith(token):
            configured = home + configured[len(token) :]
            break
    return Path(configured).expanduser().resolve()


def _apply_library_env() -> None:
    """Normalize COURTLISTENER_DATA_DIR so the shared config helpers see it."""
    library = _library_dir()
    if library:
        os.environ["COURTLISTENER_DATA_DIR"] = str(library)


@contextlib.contextmanager
def _captured_stdout():
    """Redirect library ``print`` output away from the JSON-RPC stream.

    ``courtlistener_mcp`` prints progress while paging search results. On a
    stdio transport that output would corrupt the protocol, so it is captured
    and re-emitted on stderr.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield buffer
    captured = buffer.getvalue().strip()
    if captured:
        for line in captured.splitlines():
            log(f"lib: {line}")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def tool_check_setup(_: dict[str, Any]) -> str:
    """Report every setup check, independently — a failure never hides the rest.

    Checks that depend on an earlier one (connectivity needs a key) are
    reported as skipped with the reason, not silently omitted.
    """
    from courtlistener_mcp.config import get_api_key

    lines = [
        f"CourtListener by DocketDrafter: v{SERVER_VERSION}",
        f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    ]

    missing = _missing_modules()
    if missing:
        lines.append(f"Dependencies: MISSING ({', '.join(missing)})")
        lines.append(f"  Expected them in: {VENDOR_DIR}")
        lines.append("  Reinstall the CourtListener extension, then quit and reopen Claude.")
    else:
        lines.append(f"Dependencies: OK ({', '.join(REQUIRED_MODULES)})")

    library = _library_dir()
    if library is None:
        lines.append("CourtListener Library: not configured")
        lines.append(
            "  Set the library folder in the connector settings, or the server "
            "will have nowhere persistent to save opinions."
        )
    else:
        lines.append(f"CourtListener Library: {library}")
        lines.append(
            f"Library exists: {'yes' if library.exists() else 'no (will be created)'}"
        )

    api_key = get_api_key(library)
    if api_key:
        lines.append("API key: found")
    else:
        lines.append("API key: not configured")
        lines.append("  Add your CourtListener API key in the connector settings.")
        lines.append(
            "  Create or view a free token at "
            "https://www.courtlistener.com/profile/api-token/"
        )

    if missing:
        lines.append("CourtListener connection: skipped (dependencies missing)")
    elif not api_key:
        lines.append("CourtListener connection: skipped (no API key to test with)")
    else:
        lines.append(_connectivity_check(api_key))

    return "\n".join(lines)


def _connectivity_check(api_key: str) -> str:
    """One bounded live probe against the API, classified honestly.

    A 429 is NOT a failure: it proves the network path and the key both work
    and the account is merely throttled. Reporting it as 'failed' sends users
    hunting for configuration problems that do not exist.
    """
    from courtlistener_mcp.http import HttpError, get as http_get

    try:
        # A diagnostic must answer fast: short timeout, no retries. Failing
        # quickly with an explanation beats retrying into the client's tool
        # timeout and reporting nothing.
        response = http_get(
            "https://www.courtlistener.com/api/rest/v4/clusters/",
            headers={"Authorization": f"Token {api_key}"},
            params={"page_size": 1},
            timeout=10,
            raise_for_status=False,
            retries=False,
        )
    except HttpError as exc:
        return (
            f"CourtListener connection: failed ({exc})\n"
            "  Confirm this computer can reach www.courtlistener.com and "
            "storage.courtlistener.com."
        )

    if response.status_code in {401, 403}:
        return (
            "CourtListener connection: reachable, but the API key was rejected\n"
            "  Check the key at https://www.courtlistener.com/profile/api-token/ "
            "and update it in the connector settings."
        )
    if response.status_code == 429:
        return (
            "CourtListener connection: OK, but currently rate-limited (HTTP 429)\n"
            "  The network path and API key both work; the account has hit its "
            "hourly quota. Wait a few minutes before making more requests."
        )
    if response.status_code >= 400:
        return (
            f"CourtListener connection: reachable, but the API returned "
            f"HTTP {response.status_code}\n"
            "  This is usually temporary on CourtListener's side."
        )
    return "CourtListener connection: OK"


def tool_read_search_docs(_: dict[str, Any]) -> str:
    """Return the complete bundled CourtListener search-syntax guide."""
    guide = LIB_DIR / "docs" / "courtlistener-search.txt"
    if not guide.is_file():
        raise RuntimeError(
            "The bundled CourtListener search guide is missing. Reinstall the "
            "CourtListener extension, then quit and reopen Claude."
        )
    return guide.read_text(encoding="utf-8")


def tool_search_courts(args: dict[str, Any]) -> str:
    """Search bundled court identifiers by name or location."""
    from courtlistener_mcp.courts import search_courts

    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    results = search_courts(query)
    if not results:
        return f'No courts matched: "{query}"'
    lines = [f"{len(results)} court(s) matched \"{query}\":", ""]
    lines.extend(
        f"  {court.court_id}\t{court.jurisdiction}\t{court.full_name}" for court in results
    )
    return "\n".join(lines)


def tool_check_court_ids(args: dict[str, Any]) -> str:
    """Validate one or many exact court identifiers."""
    from courtlistener_mcp.courts import get_court

    court_ids = [str(v).strip() for v in (args.get("court_ids") or []) if str(v).strip()]
    # Preserve order, drop duplicates.
    court_ids = list(dict.fromkeys(court_ids))
    if not court_ids:
        raise ValueError("court_ids is required and must contain at least one court ID")

    lines = []
    unknown = 0
    for court_id in court_ids:
        court = get_court(court_id)
        if court is None:
            unknown += 1
            lines.append(f'{court_id}\tUNKNOWN — not a CourtListener court ID')
        else:
            lines.append(f"{court.court_id}\t{court.jurisdiction}\t{court.full_name}")
    if unknown:
        lines.append("")
        lines.append(
            f"{unknown} ID(s) are not valid. Use search_courts to "
            "find the correct identifiers before searching with them."
        )
    return "\n".join(lines)


def tool_search_opinions(args: dict[str, Any]) -> str:
    """Search opinions without downloading them."""
    from courtlistener_mcp.courts import require_court
    from courtlistener_mcp.http import get as http_get
    from courtlistener_mcp.sources.courtlistener import API_BASE_URL, auth_headers

    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = _clamped(args, "limit", default=10, low=1, high=50)
    params = {"q": query, "type": "o"}

    preamble = []
    court_id = args.get("court")
    if court_id:
        court = require_court(str(court_id))
        params["court"] = court.court_id
        preamble.append(f"Court filter resolved: {court.court_id} — {court.full_name}")

    with _captured_stdout():
        response = http_get(
            f"{API_BASE_URL}/search/", headers=auth_headers(), params=params, timeout=60
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not results:
        return "\n".join(preamble + ["No results found."])

    lines = preamble + [
        f"Found {data.get('count', len(results))} results "
        f"(showing first {min(len(results), limit)}):",
        "",
    ]
    for result in results[:limit]:
        citations = ", ".join(result.get("citation", []) or [])
        status = result.get("status") or result.get("precedentialStatus") or "?"
        url = f"https://www.courtlistener.com{result.get('absolute_url', '')}"
        lines.append(
            f"  {result.get('caseName', '?')}  [{citations}]  "
            f"({result.get('court', '?')}, {result.get('dateFiled', '?')}, {status})\n"
            f"    {url}"
        )
    return "\n".join(lines)


def _gather_opinion_jobs(args: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect (kind, value) jobs from the citations and urls arrays."""
    jobs: list[tuple[str, str]] = []
    for plural, kind in (("citations", "citation"), ("urls", "url")):
        for value in args.get(plural) or []:
            if str(value).strip():
                jobs.append((kind, str(value)))
    # De-duplicate while preserving order; a brief often cites a case twice.
    seen: set[tuple[str, str]] = set()
    return [job for job in jobs if not (job in seen or seen.add(job))]


MAX_OPINIONS_PER_CALL = 50


def tool_get_opinions(args: dict[str, Any]) -> str:
    """Retrieve one or many opinions and save them to the library."""
    from courtlistener_mcp.http import HttpError
    from courtlistener_mcp.sources.courtlistener import (
        CitationNotFoundError,
        MultipleCitationMatchesError,
        fetch_by_citation,
        fetch_by_url,
    )

    jobs = _gather_opinion_jobs(args)
    if not jobs:
        raise ValueError("provide at least one citation or url")
    if len(jobs) > MAX_OPINIONS_PER_CALL:
        raise ValueError(
            f"{len(jobs)} requested; the maximum per call is {MAX_OPINIONS_PER_CALL}. "
            "Split the request, or use download_search_results for "
            "a whole search result set."
        )

    _apply_library_env()
    library = _library_dir()
    output_dir = library / "cases" if library else None
    refresh = bool(args.get("refresh", False))

    results: list[dict[str, Any]] = []
    effective_library = library
    for kind, value in jobs:
        entry: dict[str, Any] = {"requested": value}
        try:
            with _captured_stdout():
                saved = (
                    fetch_by_citation(value, output_dir=output_dir, refresh=refresh)
                    if kind == "citation"
                    else fetch_by_url(value, output_dir=output_dir, refresh=refresh)
                )
        except MultipleCitationMatchesError as exc:
            entry.update(status="ambiguous", detail=str(exc))
        except CitationNotFoundError as exc:
            entry.update(status="not_found", detail=str(exc))
        except (HttpError, ValueError) as exc:
            # One bad item must not lose the rest of the batch.
            entry.update(status="error", detail=str(exc))
        else:
            # Return the library root once and only the Markdown path agents
            # need to read. Repeating absolute directory, HTML, and metadata
            # paths for every batch item wastes substantial context.
            if effective_library is None:
                effective_library = saved.path.parent.parent
            try:
                opinion_path = (saved.path / "opinion.md").relative_to(effective_library)
            except ValueError:
                # Defensive fallback for a custom backend that saves elsewhere.
                opinion_path = saved.path / "opinion.md"
            entry.update(
                status=saved.status,
                case_name=saved.description,
                source_url=saved.source_url,
                opinion_path=str(opinion_path),
            )
        results.append(entry)

    counts: dict[str, int] = {}
    for entry in results:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    payload: dict[str, Any] = {"summary": counts}
    if effective_library is not None:
        payload["library_root"] = str(effective_library)
    payload["results"] = results
    return json.dumps(payload, separators=(",", ":"))


def tool_verify_citations(args: dict[str, Any]) -> str:
    """Batch existence check for citations, without downloading anything."""
    from courtlistener_mcp.sources.courtlistener import verify_citations_in_text

    text = str(args.get("text", "")).strip()
    citations = [str(c).strip() for c in (args.get("citations") or []) if str(c).strip()]
    if bool(text) == bool(citations):
        raise ValueError("provide exactly one of text or citations")
    if citations:
        text = "\n".join(citations)

    with _captured_stdout():
        results = verify_citations_in_text(text)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return json.dumps(
        {
            "summary": counts,
            "results": results,
            "scope_note": (
                "Existence check only: 'found' means the citation resolves to a "
                "real case in CourtListener. It does NOT confirm the case "
                "supports any proposition (read it via get_opinions) or that it "
                "is still good law (no citator signal exists here)."
            ),
        },
        indent=2,
    )


def tool_search_recap(args: dict[str, Any]) -> str:
    """Search RECAP dockets and filings without downloading PDFs."""
    from courtlistener_mcp.courts import require_court
    from courtlistener_mcp.http import get as http_get
    from courtlistener_mcp.sources.courtlistener import API_BASE_URL, auth_headers

    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = _clamped(args, "limit", default=10, low=1, high=50)
    params = {"q": query, "type": "r"}

    preamble = []
    court_id = args.get("court")
    if court_id:
        court = require_court(str(court_id))
        params["court"] = court.court_id
        preamble.append(f"Court filter resolved: {court.court_id} — {court.full_name}")

    with _captured_stdout():
        response = http_get(
            f"{API_BASE_URL}/search/", headers=auth_headers(), params=params, timeout=60
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not results:
        return "\n".join(preamble + ["No results found."])

    lines = preamble + [
        f"Found {data.get('count', len(results))} results "
        f"(showing first {min(len(results), limit)}):",
        "",
    ]
    for index, result in enumerate(results[:limit], start=1):
        case_name = result.get("caseName") or result.get("case_name") or "?"
        docket_id = result.get("docket_id") or result.get("docketId") or result.get("docket")
        lines.append(f"{index}. {case_name}")
        lines.append(
            f"   Court/date: {result.get('court') or result.get('court_id') or '?'}, "
            f"filed {result.get('dateFiled') or result.get('date_filed') or '?'}"
        )
        if docket_number := (result.get("docketNumber") or result.get("docket_number")):
            lines.append(f"   Docket number: {docket_number}")
        if docket_id:
            lines.append(f"   Docket ID: {docket_id}")
        documents = result.get("recap_documents") or []
        if documents:
            lines.append("   Matching filing records:")
        for doc in documents:
            entry_number = doc.get("entry_number")
            document_number = doc.get("document_number")
            attachment_number = doc.get("attachment_number")
            identity = f"     Entry {entry_number if entry_number is not None else '?'}"
            if document_number not in (None, ""):
                identity += f", document {document_number}"
            if attachment_number not in (None, ""):
                identity += f", attachment {attachment_number}"
            identity += f", RECAP document ID {doc.get('id', '?')}"
            lines.append(identity)
            description = _clean_docket_description(
                doc.get("short_description") or doc.get("description"), 180
            )
            if description:
                lines.append(f"       {description}")
            filepath = str(doc.get("filepath_local") or "")
            if doc.get("is_available") and filepath:
                download_url = (
                    filepath
                    if filepath.startswith(("http://", "https://"))
                    else f"https://storage.courtlistener.com/{filepath.lstrip('/')}"
                )
                lines.append(f"       PDF: {download_url}")
            elif doc.get("is_available") is not None:
                lines.append("       PDF: not available in RECAP")
        if (result.get("meta") or {}).get("more_docs"):
            lines.append(
                "   More matching filing records exist. Use an entry number "
                "shown above with targeted get_docket, or narrow the search."
            )
        if absolute_url := result.get("docket_absolute_url"):
            lines.append(f"   Docket: https://www.courtlistener.com{absolute_url}")
        lines.append("")
    return "\n".join(lines)


def _clamped(args: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    """Read an integer argument, clamped to a sane range."""
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


def _resolve_docket(
    args: dict[str, Any], cache_dir: Path | None, *, use_cache: bool = True
) -> dict[str, Any]:
    """Resolve a docket from any of the four supported identifier forms."""
    from courtlistener_mcp.sources.recap import (
        fetch_docket,
        fetch_docket_by_pacer_case_id,
        parse_docket_url,
        parse_recap_storage_url,
    )

    docket_id = args.get("docket_id")
    url = args.get("url")
    recap_url = args.get("recap_url")
    pacer_case_id = args.get("pacer_case_id")
    court_id = args.get("court_id")

    provided = [bool(docket_id), bool(url), bool(recap_url), bool(pacer_case_id)]
    if sum(provided) != 1:
        raise ValueError(
            "provide exactly one of docket_id, url, recap_url, or pacer_case_id"
        )

    if url:
        return fetch_docket(
            parse_docket_url(str(url)), cache_dir=cache_dir, use_cache=use_cache
        )
    if recap_url:
        resolved_court, resolved_case = parse_recap_storage_url(str(recap_url))
        return fetch_docket_by_pacer_case_id(
            resolved_court, resolved_case, cache_dir=cache_dir, use_cache=use_cache
        )
    if pacer_case_id:
        if not court_id:
            raise ValueError("court_id is required when using pacer_case_id")
        return fetch_docket_by_pacer_case_id(
            str(court_id), str(pacer_case_id), cache_dir=cache_dir, use_cache=use_cache
        )
    return fetch_docket(int(docket_id), cache_dir=cache_dir, use_cache=use_cache)


def _collect_documents(
    docket_id: int,
    args: dict[str, Any],
    cache_dir: Path | None,
    *,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Gather docket entries and flattened documents, honouring targeting flags.

    Targeted fetches hit narrower endpoints than a full docket walk, which
    matters on dockets with hundreds of entries.
    """
    from courtlistener_mcp.sources.recap import (
        fetch_docket_entries_by_numbers,
        fetch_recap_documents_by_ids,
        fetch_recap_documents_by_numbers,
        flatten_documents,
        flatten_recap_documents,
    )

    entry_numbers = [int(n) for n in (args.get("entry_numbers") or [])]
    document_numbers = [int(n) for n in (args.get("document_numbers") or [])]
    recap_document_ids = [int(n) for n in (args.get("recap_document_ids") or [])]

    entries: list[dict[str, Any]] = []
    documents: list[Any] = []

    if entry_numbers:
        entries = fetch_docket_entries_by_numbers(
            docket_id, entry_numbers, cache_dir=cache_dir, use_cache=use_cache
        )
        documents.extend(flatten_documents(docket_id, entries))
    if document_numbers:
        recap_documents = fetch_recap_documents_by_numbers(
            docket_id, document_numbers, cache_dir=cache_dir, use_cache=use_cache
        )
        documents.extend(flatten_recap_documents(docket_id, recap_documents))
    if recap_document_ids:
        recap_documents = fetch_recap_documents_by_ids(
            docket_id, recap_document_ids, cache_dir=cache_dir, use_cache=use_cache
        )
        documents.extend(flatten_recap_documents(docket_id, recap_documents))

    deduped: list[Any] = []
    seen: set[int] = set()
    for doc in documents:
        if doc.document_id in seen:
            continue
        seen.add(doc.document_id)
        deduped.append(doc)
    return entries, deduped


def _encode_docket_cursor(url: str | None) -> str | None:
    if not url:
        return None
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _decode_docket_cursor(cursor: str, docket_id: int) -> str:
    try:
        padding = "=" * (-len(cursor) % 4)
        url = base64.urlsafe_b64decode(cursor + padding).decode()
    except Exception as exc:
        raise ValueError("Invalid docket-entry cursor.") from exc
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.courtlistener.com"
        or parsed.path != "/api/rest/v4/docket-entries/"
        or query.get("docket") != [str(docket_id)]
    ):
        raise ValueError("Invalid docket-entry cursor for this docket.")
    return url


def _clean_docket_description(value: Any, limit: int = 300) -> str:
    """Remove PACER boilerplate and cap entry descriptions for tool context."""
    import re

    text = " ".join(str(value or "").split())
    for marker in (
        r"\s+Document filed by\b",
        r"\s+Filed In Associated Cases:",
        r"\s*\(Attachments?:",
        r"\s*\(Entered:",
    ):
        text = re.split(marker, text, maxsplit=1, flags=re.IGNORECASE)[0]
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _docket_entry_summaries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for entry in entries:
        raw_docs = entry.get("recap_documents") or entry.get("documents") or []
        docs = [doc for doc in raw_docs if isinstance(doc, dict)]
        downloadable: list[dict[str, Any]] = []
        for doc in docs:
            if not (doc.get("is_available") and doc.get("filepath_local")):
                continue
            attachment_number = doc.get("attachment_number")
            filepath = str(doc.get("filepath_local") or "")
            item: dict[str, Any] = {
                "recap_document_id": doc.get("id"),
                "document_number": doc.get("document_number") or "",
                "description": _clean_docket_description(
                    doc.get("description") or doc.get("short_description"), 120
                ),
                "is_main_document": attachment_number in (None, ""),
            }
            if filepath:
                item["url"] = (
                    filepath
                    if filepath.startswith(("http://", "https://"))
                    else f"https://storage.courtlistener.com{filepath}"
                )
            if attachment_number not in (None, ""):
                item["attachment_number"] = attachment_number
            downloadable.append(item)
        summary: dict[str, Any] = {
            "entry_number": entry.get("entry_number"),
            "date": entry.get("date_filed") or entry.get("date_created") or "",
            "description": _clean_docket_description(entry.get("description")),
            "downloadable_documents": downloadable,
        }
        attachment_count = sum(
            doc.get("attachment_number") not in (None, "") for doc in docs
        )
        if attachment_count:
            summary["attachment_count"] = attachment_count
        summaries.append({k: v for k, v in summary.items() if v not in (None, "", [])})
    return summaries


def tool_get_docket(args: dict[str, Any]) -> str:
    """Browse one concise, native-order RECAP docket range."""
    from courtlistener_mcp.config import ensure_directory
    from courtlistener_mcp.sources.recap import (
        default_cache_dir,
        docket_output_dir,
        fetch_docket_entries_page,
        flatten_documents,
        write_json,
        write_manifest,
    )

    _apply_library_env()
    library = _library_dir()
    cache_dir = default_cache_dir(library) if library else None
    use_cache = not bool(args.get("refresh", False))

    # RECAP progress logs go to stderr, which is safe for the MCP transport and
    # avoids process-wide stdout redirection while this worker remains active.
    docket = _resolve_docket(args, cache_dir, use_cache=use_cache)
    docket_id = int(docket["id"])
    targeted = bool(
        args.get("entry_numbers")
        or args.get("document_numbers")
        or args.get("recap_document_ids")
    )
    cursor = args.get("cursor")
    if targeted and cursor:
        raise ValueError("cursor cannot be combined with entry_numbers or document_numbers")
    next_cursor = None
    total_entries: int | None = None
    if targeted:
        entries, documents = _collect_documents(
            docket_id, args, cache_dir, use_cache=use_cache
        )
    else:
        entries, total_entries, next_url = fetch_docket_entries_page(
            docket_id,
            next_url=_decode_docket_cursor(cursor, docket_id) if cursor else None,
            page_size=_clamped(args, "limit", default=10, low=1, high=25),
            cache_dir=cache_dir,
            use_cache=use_cache,
        )
        documents = flatten_documents(docket_id, entries)
        next_cursor = _encode_docket_cursor(next_url)

    out_dir = None
    if library is not None:
        out_dir = ensure_directory(docket_output_dir(docket, data_dir=library))
        write_json(out_dir / "docket.json", docket)
        write_json(out_dir / "entries.json", entries)
        write_manifest(out_dir / "manifest.md", docket=docket, docs=documents)

    payload: dict[str, Any] = {
        "docket_id": docket_id,
        "case_name": docket.get("case_name") or "",
        "court_id": docket.get("court_id") or "",
        "docket_number": docket.get("docket_number") or "",
        "entries": _docket_entry_summaries(entries),
    }
    if total_entries is not None:
        payload["total_entries"] = total_entries
    if next_cursor:
        payload["next_cursor"] = next_cursor
    if out_dir:
        payload["saved_to"] = str(out_dir)
    return json.dumps(
        {k: v for k, v in payload.items() if v not in (None, "", [])},
        separators=(",", ":"),
    )


def tool_download_docket_pdfs(args: dict[str, Any]) -> str:
    """Download selected RECAP PDFs into the library."""
    from courtlistener_mcp.config import ensure_directory
    from courtlistener_mcp.sources.recap import (
        default_cache_dir,
        docket_output_dir,
        download_document,
        pdf_filename,
        write_json,
        write_manifest,
    )

    _apply_library_env()
    library = _library_dir()
    if library is None:
        raise ValueError(
            "No CourtListener Library folder is configured. Set it in the "
            "connector settings before downloading PDFs."
        )
    cache_dir = default_cache_dir(library)
    overwrite = bool(args.get("overwrite", False))
    use_cache = not bool(args.get("refresh", False))
    max_pdfs = _clamped(args, "max_pdfs", default=25, low=1, high=200)
    exact_ids = [int(n) for n in (args.get("recap_document_ids") or [])]
    if not (args.get("entry_numbers") or args.get("document_numbers") or exact_ids):
        raise ValueError(
            "select entry_numbers, document_numbers, or recap_document_ids; "
            "downloading an entire docket is not allowed"
        )
    include_attachments = bool(args.get("include_attachments", False))

    with _captured_stdout():
        docket = _resolve_docket(args, cache_dir, use_cache=use_cache)
        docket_id = int(docket["id"])
        entries, documents = _collect_documents(
            docket_id, args, cache_dir, use_cache=use_cache
        )
        # Entry and visible document numbers can match many attachments. Keep
        # only main documents unless attachments were explicitly requested.
        # Exact RECAP IDs are already unambiguous and may identify an attachment.
        if not include_attachments and not exact_ids:
            documents = [
                doc for doc in documents if doc.attachment_number in (None, "")
            ]

        out_dir = ensure_directory(docket_output_dir(docket, data_dir=library))
        pdf_dir = ensure_directory(out_dir / "pdfs")
        saved: dict[int, Path] = {}
        reused = 0
        unavailable = 0
        remaining: list[Any] = []
        for doc in documents:
            # The cap counts new network downloads only. Files already on disk
            # are free to acknowledge, and skipping them would make repeated
            # calls report less and less while doing the same work.
            already = (pdf_dir / pdf_filename(doc)).exists() and not overwrite
            new_downloads = len(saved) - reused
            if not already and new_downloads >= max_pdfs:
                if doc.is_available and doc.filepath_local:
                    remaining.append(doc)
                else:
                    unavailable += 1
                continue
            path = download_document(doc, pdf_dir, overwrite=overwrite)
            if path:
                saved[doc.document_id] = path
                if already:
                    reused += 1
            else:
                unavailable += 1
        write_json(out_dir / "docket.json", docket)
        write_json(out_dir / "entries.json", entries)
        write_manifest(
            out_dir / "manifest.md", docket=docket, docs=documents, pdf_paths=saved
        )

    lines = [
        f"Docket {docket_id}: {docket.get('case_name', '?')}",
        f"Saved to: {pdf_dir}",
        "",
        f"Newly downloaded: {len(saved) - reused}   Already saved: {reused}   "
        f"Not available in RECAP: {unavailable}",
    ]
    if remaining:
        lines.append("")
        lines.append(
            f"STOPPED AT THE {max_pdfs}-PDF LIMIT: {len(remaining)} available "
            "PDF(s) were NOT downloaded. Tell the user the download is partial. "
            "To continue, call this tool again (already-saved files are skipped "
            "automatically), or target specific filings with entry_numbers."
        )
        lines.append("Not yet downloaded:")
        lines.extend(f"  {doc.label}" for doc in remaining[:20])
        if len(remaining) > 20:
            lines.append(f"  ... and {len(remaining) - 20} more")
    lines.extend(f"  {path}" for path in list(saved.values())[:50])
    if len(saved) > 50:
        lines.append(f"  ... and {len(saved) - 50} more")
    return "\n".join(lines)


def tool_download_search_results(args: dict[str, Any]) -> str:
    """Inspect or bulk-download the opinions matching a query or search URL."""
    from urllib.parse import urlencode

    from courtlistener_mcp.courts import require_court
    from courtlistener_mcp.sources.courtlistener import (
        COURTLISTENER_BASE_URL,
        fetch_search_results,
        parse_search_url,
        search_opinions,
    )

    search_url = str(args.get("search_url", "")).strip()
    query = str(args.get("query", "")).strip()
    if bool(search_url) == bool(query):
        raise ValueError("provide exactly one of query or search_url")
    limit = _clamped(args, "limit", default=25, low=1, high=200)
    download = bool(args.get("download", False))

    if query:
        params = {"q": query, "type": "o"}
        if court_id := args.get("court"):
            params["court"] = require_court(str(court_id)).court_id
        # fetch_search_results takes a URL, so a query becomes the same URL a
        # user would build on courtlistener.com.
        search_url = f"{COURTLISTENER_BASE_URL}/?{urlencode(params)}"

    _apply_library_env()
    library = _library_dir()

    if not download:
        params = parse_search_url(search_url)
        if params.get("type") != "o":
            params["type"] = "o"
        with _captured_stdout():
            results = search_opinions(params, max_results=limit)
        if not results:
            return "No results found for that search URL."
        lines = [
            f"Showing {len(results)} opinions from that search "
            f"(capped at {limit}; there may be more). "
            "Call again with download=true to save them.",
            "",
        ]
        for result in results[:limit]:
            citations = ", ".join(result.get("citation", []) or [])
            lines.append(
                f"  {result.get('caseName', '?')}  [{citations}]  "
                f"({result.get('court', '?')}, {result.get('dateFiled', '?')})\n"
                f"    https://www.courtlistener.com{result.get('absolute_url', '')}"
            )
        return "\n".join(lines)

    if library is None:
        raise ValueError(
            "No CourtListener Library folder is configured. Set it in the "
            "connector settings before downloading opinions."
        )
    with _captured_stdout():
        saved = fetch_search_results(
            search_url,
            output_dir=library / "cases",
            limit=limit,
            skip_existing=bool(args.get("skip_existing", True)),
        )
    lines = [f"Saved {len(saved)} opinions to {library / 'cases'}", ""]
    lines.extend(f"  {item.description} -> {item.path}" for item in saved[:50])
    if len(saved) > 50:
        lines.append(f"  ... and {len(saved) - 50} more")
    return "\n".join(lines)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_setup",
        "description": (
            "Check that CourtListener is ready to use: Python, dependencies, the "
            "library folder, the API key, and live connectivity. Run this first "
            "if any other tool reports a configuration problem."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_check_setup,
    },
    {
        "name": "read_search_docs",
        "description": (
            "Read the complete CourtListener query-syntax guide. You MUST call this "
            "before the first search_opinions, search_recap, or "
            "download_search_results call in each conversation, even for a "
            "simple search. Read the complete output before constructing the "
            "first query; one reading per conversation is sufficient."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": tool_read_search_docs,
    },
    {
        "name": "search_courts",
        "description": (
            "Find CourtListener court IDs by name or location. Always resolve a "
            "court ID with this tool before filtering a search by court. Never "
            "assume a state abbreviation covers every court in that state: 'ny' "
            "is valid but means only the New York Court of Appeals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Court name or location, e.g. "New York" or "ninth circuit"',
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "handler": tool_search_courts,
    },
    {
        "name": "check_court_ids",
        "description": (
            "Validate one or many exact CourtListener court IDs and return their "
            "full names. Validate every ID in a query expression like "
            "court_id:(nysd OR nyed) in a single call. Unknown IDs are flagged "
            "per item without failing the rest."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "court_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Exact court IDs, e.g. ["nyappdiv", "nysd"]',
                },
            },
            "required": ["court_ids"],
            "additionalProperties": False,
        },
        "handler": tool_check_court_ids,
    },
    {
        "name": "search_opinions",
        "description": (
            "Search CourtListener opinions without downloading them. REQUIRED: call "
            "read_search_docs once before the first CourtListener search in "
            "each conversation and use its guidance for every query. Search "
            "results are metadata only: NEVER characterize an opinion's holding, "
            "importance, reasoning, or support for a proposition until you have "
            "retrieved it with get_opinions and read its text. Review the case "
            "name, citation, court, date, and status before selecting a "
            "result. Hyperlink every opinion you mention to its CourtListener "
            "URL. To save results, use get_opinions (one case) or "
            "download_search_results (many) — saving is automatic "
            "to the configured library; no folder setup is needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Search query, e.g. caseName:"Cosby" or a natural phrase',
                },
                "court": {
                    "type": "string",
                    "description": "Optional court ID filter; validate it first with search_courts",
                },
                "limit": {"type": "integer", "description": "Maximum results to show (default 10)"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "handler": tool_search_opinions,
    },
    {
        "name": "get_opinions",
        "description": (
            "Retrieve one or MANY opinions by citation and/or CourtListener URL "
            "in a single call — pass every citation from a brief or search "
            "review at once instead of calling repeatedly. Returns per-item "
            "results; one failed lookup never aborts the rest. Opinions are "
            "saved automatically to the user's configured CourtListener Library "
            "folder — never ask the user where to put files or request folder "
            "access. Reuses saved copies; report 'already_saved' as already in "
            "the library, not as a new download. Before discussing an opinion, "
            "read the file at library_root/opinion_path; 'already_saved' does "
            "not mean it has been read in this conversation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Reporter citations, e.g. ["576 U.S. 644", "5 F.3d 100"]. Retrieve every case a document cites in ONE call — never loop one citation at a time.',
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CourtListener opinion URLs; may be combined with citations",
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Download again even if already saved (default false)",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_get_opinions,
    },
    {
        "name": "verify_citations",
        "description": (
            "Check whether citations resolve to real cases — a whole brief in "
            "one call. Pass the document text (citations are extracted "
            "server-side) or an explicit list. Returns found / not_found / "
            "ambiguous per citation with the matching case names and URLs. "
            "Existence only: this does NOT confirm what a case holds (use "
            "get_opinions and read it) or that it is still good law. Nothing "
            "is downloaded; use get_opinions when the user needs the opinions "
            "themselves."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Document text to scan for citations (up to 50,000 characters). Provide this or citations, not both.",
                },
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Explicit citations to check, e.g. ["576 U.S. 644"]. Provide this or text, not both.',
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_verify_citations,
    },
    {
        "name": "search_recap",
        "description": (
            "Search RECAP dockets and filings without downloading PDFs. REQUIRED: call "
            "read_search_docs once before the first CourtListener search in "
            "each conversation and use its guidance for every query. Party and attorney "
            "fields describe the docket, not necessarily an individual filing. "
            "Use docket_id plus short_description to locate a filing without "
            "downloading it (for example short_description:(complaint)); results "
            "expose entry numbers, exact RECAP document IDs, attachment "
            "numbers, and direct PDF URLs when available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'RECAP query, e.g. party:("Microsoft Corporation")',
                },
                "court": {"type": "string", "description": "Optional validated court ID filter"},
                "limit": {"type": "integer", "description": "Maximum results to show (default 10)"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "handler": tool_search_recap,
    },
    {
        "name": "get_docket",
        "description": (
            "Browse a concise range of RECAP docket entries without downloading "
            "PDFs. Use this untargeted mode for a docket overview, nearby "
            "procedural context, or fallback after filing search fails—not to "
            "locate a specific filing. Specific-filings workflow for EVERY "
            "docket: search_recap with docket_id plus short_description terms, "
            "then confirm the selected entry with targeted get_docket. Defaults "
            "to 10 native-order entries; limit is 1–25 with a hard maximum of "
            "25, and there is no sort option. "
            "Descriptions are shortened and only downloadable documents are "
            "listed. Saves docket.json, entries.json, and a readable manifest "
            "automatically to the user's configured CourtListener "
            "Library folder — never ask the user where to put files. Identify "
            "the docket by exactly one of docket_id, url, recap_url, or "
            "pacer_case_id (with court_id). Pass next_cursor back as cursor only "
            "when more procedural context is needed. Do not browse pages merely "
            "to find a specific filing. NEVER guess an "
            "entry or document number—for example, never assume a complaint is entry 1. "
            "Inspect the actual docket entries first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "docket_id": {"type": "integer", "description": "CourtListener docket ID"},
                "url": {"type": "string", "description": "CourtListener public docket URL"},
                "recap_url": {
                    "type": "string",
                    "description": "A storage.courtlistener.com RECAP document URL",
                },
                "pacer_case_id": {"type": "string", "description": "PACER case ID"},
                "court_id": {
                    "type": "string",
                    "description": "Court ID for pacer_case_id, e.g. nysd (required with it)",
                },
                "entry_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Fetch only these docket entry numbers",
                },
                "document_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Fetch only these visible PACER document numbers",
                },
                "recap_document_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Fetch exact RECAP document IDs supplied by search_recap or an earlier get_docket result",
                },
                "cursor": {
                    "type": "string",
                    "description": "Opaque next_cursor from the preceding get_docket result; use with docket_id",
                },
                "limit": {
                    "type": "integer",
                    "description": "Entries requested per range (default 10, hard maximum 25)",
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Fetch fresh docket data from CourtListener instead of the local cache. Use when the case is active and new filings are expected (default false)",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_get_docket,
    },
    {
        "name": "download_docket_pdfs",
        "description": (
            "Download RECAP PDFs for a docket. They are saved automatically to "
            "the user's configured CourtListener Library folder — never ask the "
            "user where to put files. Before EVERY download, you MUST inspect "
            "the actual docket with get_docket and identify the filing from "
            "CourtListener's entry description and document metadata. NEVER "
            "guess or infer entry_numbers or document_numbers—for example, "
            "NEVER assume a complaint is entry 1. A prior get_docket result in "
            "this conversation may be reused. Prefer exact recap_document_ids. "
            "Entry/document selections download main documents only by default; "
            "set include_attachments=true only when the user wants attachments. "
            "A selection is mandatory; whole-docket downloads are rejected."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "docket_id": {"type": "integer", "description": "CourtListener docket ID"},
                "url": {"type": "string", "description": "CourtListener public docket URL"},
                "recap_url": {
                    "type": "string",
                    "description": "A storage.courtlistener.com RECAP document URL",
                },
                "pacer_case_id": {"type": "string", "description": "PACER case ID"},
                "court_id": {
                    "type": "string",
                    "description": "Court ID for pacer_case_id, e.g. nysd (required with it)",
                },
                "entry_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Download only these docket entry numbers",
                },
                "document_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Download main documents with these visible PACER document numbers",
                },
                "recap_document_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Preferred: exact RECAP document IDs from search_recap or get_docket; may select a specific attachment",
                },
                "include_attachments": {
                    "type": "boolean",
                    "description": "Also download attachments when selecting by entry/document number (default false); exact RECAP IDs are always honored",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace existing PDFs (default false)",
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Fetch fresh docket data from CourtListener instead of the local cache. Use when the case is active and new filings are expected (default false)",
                },
                "max_pdfs": {
                    "type": "integer",
                    "description": "Maximum NEW downloads per call (default 50, max 200). If the docket has more, the result names what was left and the call can simply be repeated — already-saved files are skipped automatically.",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_download_docket_pdfs,
    },
    {
        "name": "download_search_results",
        "description": (
            "Build or extend the user's research library in bulk: inspect or "
            "download every opinion matching a search. REQUIRED: call "
            "read_search_docs once before the first CourtListener search in "
            "each conversation and use its guidance for every query. Give either a query (with "
            "optional court) or a courtlistener.com search URL. Call with "
            "download=false first to see what matches, then download=true to "
            "save them — opinions are saved automatically to the user's "
            "configured CourtListener Library folder; never ask the user where "
            "to put files. For specific known cases use get_opinions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": 'Search query, e.g. "merchant cash advance". Provide this or search_url, not both.',
                },
                "court": {
                    "type": "string",
                    "description": "Optional court ID filter for query; validate it first with search_courts",
                },
                "search_url": {
                    "type": "string",
                    "description": "A courtlistener.com search URL, e.g. https://www.courtlistener.com/?q=...&type=o. Provide this or query, not both.",
                },
                "download": {
                    "type": "boolean",
                    "description": "false (default) inspects only; true saves the opinions",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum opinions to show or download (default 25)",
                },
                "skip_existing": {
                    "type": "boolean",
                    "description": "Skip opinions already in the library (default true)",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_download_search_results,
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _public_tools() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in tool.items() if k != "handler"}
        for tool in TOOLS
    ]


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class HttpError(Exception):
    """Placeholder rebound to courtlistener_mcp.http.HttpError when deps load."""


try:
    from courtlistener_mcp.http import HttpError  # noqa: F811
except ImportError:
    pass  # DEPENDENCIES_MISSING already explains; tools short-circuit before use


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC message, returning a response or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    if method in {"notifications/initialized", "initialized"}:
        return None

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": _public_tools()})

    if method == "tools/call":
        name = params.get("name")
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        blocked = PYTHON_TOO_OLD or DEPENDENCIES_MISSING
        if blocked:
            return _result(
                request_id,
                {"content": [{"type": "text", "text": blocked}], "isError": True},
            )
        try:
            text = tool["handler"](arguments)
        except HttpError as exc:
            if exc.status_code == 429:
                text = (
                    "CourtListener is rate-limiting this account right now. The "
                    "connector already waited and retried automatically, so tell "
                    "the user to pause for a few minutes before continuing. Bulk "
                    "downloads count against the account's hourly quota — prefer "
                    "smaller, targeted requests when resuming."
                )
            else:
                text = f"CourtListener request failed: {exc}"
            log(f"tool {name} http failure: {exc}")
            return _result(
                request_id,
                {"content": [{"type": "text", "text": text}], "isError": True},
            )
        except Exception as exc:  # surfaced to the model, not raised into the transport
            log(f"tool {name} failed: {exc}\n{traceback.format_exc()}")
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                },
            )
        return _result(request_id, {"content": [{"type": "text", "text": text}]})

    if request_id is None:
        return None
    return _error(request_id, -32601, f"Method not found: {method}")


def main() -> None:
    log(f"starting v{SERVER_VERSION} (python {sys.version.split()[0]}, lib {LIB_DIR})")
    _scrub_unresolved_templates()
    _apply_library_env()
    library = _library_dir()
    log(f"library: {library or 'not configured'}")
    log(f"api key: {'present' if os.getenv('COURTLISTENER_API_KEY') else 'absent'}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"skipping unparseable line: {exc}")
            continue

        try:
            response = handle_request(message)
        except Exception as exc:
            log(f"dispatch failed: {exc}\n{traceback.format_exc()}")
            response = _error(message.get("id"), -32603, f"Internal error: {exc}")

        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
