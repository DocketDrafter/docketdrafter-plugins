"""CourtListener fetch logic."""

from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from courtlistener_mcp.config import (
    ensure_directory,
    get_api_key,
    get_data_dir,
    write_text_atomic,
)
from courtlistener_mcp.http import HttpError, get, post
from courtlistener_mcp.models import SavedSource
from courtlistener_mcp.text import sanitize_filename

API_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
COURTLISTENER_BASE_URL = "https://www.courtlistener.com"


def log(message: str) -> None:
    """Print a progress line immediately.

    Progress goes to stderr, never stdout: on a stdio MCP transport stdout
    carries the JSON-RPC stream, and anything else written there corrupts the
    protocol. Keeping progress on stderr is also what lets the server dispatch
    requests concurrently — a process-wide stdout redirect could not be made
    thread-safe.
    """
    print(message, file=sys.stderr, flush=True)


class CitationNotFoundError(Exception):
    """Raised when a citation cannot be found."""


class MultipleCitationMatchesError(Exception):
    """Raised when a citation lookup yields multiple likely matches."""

    def __init__(self, message: str, clusters: list[dict] | None = None):
        super().__init__(message)
        self.clusters = clusters or []


def require_api_key() -> str:
    api_key = get_api_key()
    if not api_key:
        raise ValueError(
            "No CourtListener API key is configured. Open Claude's settings, "
            "find the CourtListener extension, and add your API key there. "
            "Get a free key at https://www.courtlistener.com/profile/api-token/"
        )
    return api_key


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Token {require_api_key()}"}


def parse_year_from_citation(citation: str) -> int | None:
    match = re.search(r"[\(\[](\d{4})[\)\]]", citation)
    if match:
        return int(match.group(1))
    match = re.search(r",\s*(\d{4})\s*$", citation)
    if match:
        return int(match.group(1))
    return None


def parse_opinion_url(url: str) -> int:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "opinion":
        return int(parts[1])
    raise ValueError(f"Could not extract cluster ID from URL: {url}")


def format_cluster_for_display(cluster: dict) -> str:
    case_name = cluster.get("case_name", "Unknown")
    date_filed = cluster.get("date_filed", "Unknown date")
    court_url = cluster.get("court", "")
    court_id = court_url.rstrip("/").split("/")[-1] if court_url else "unknown"
    absolute_url = cluster.get("absolute_url", "")
    full_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else "N/A"
    return f"  - {case_name} ({date_filed}) [{court_id}]\n    {full_url}"


def lookup_citation(citation: str) -> int:
    response = post(
        f"{API_BASE_URL}/citation-lookup/",
        headers=auth_headers(),
        data={"text": citation},
    )
    results = response.json()
    if not results:
        raise CitationNotFoundError(
            f"No citation found in text: '{citation}'. Make sure the citation format is valid."
        )

    result = results[0]
    status = result.get("status")

    if status == 200:
        clusters = result.get("clusters", [])
        if not clusters:
            raise CitationNotFoundError(
                f"Citation '{citation}' was parsed but no matching case was found."
            )
        return clusters[0]["id"]

    if status == 300:
        clusters = result.get("clusters", [])
        year = parse_year_from_citation(citation)
        if year:
            matching_clusters = [
                cluster
                for cluster in clusters
                if cluster.get("date_filed", "").startswith(str(year))
            ]
            if len(matching_clusters) == 1:
                return matching_clusters[0]["id"]
            if matching_clusters:
                clusters = matching_clusters

        raise MultipleCitationMatchesError(
            f"Citation '{citation}' matches multiple cases:\n"
            + "\n".join(format_cluster_for_display(cluster) for cluster in clusters)
            + "\n\nChoose one of the listed URLs and rerun with --url.",
            clusters=clusters,
        )

    if status == 404:
        raise CitationNotFoundError(
            f"Citation '{result.get('citation', citation)}' not found in CourtListener's database."
        )
    if status == 400:
        raise ValueError(
            f"Invalid citation format: '{citation}'. "
            f"Error: {result.get('error_message', 'Unknown error')}"
        )
    raise ValueError(
        f"Unexpected status {status} for citation '{citation}': "
        f"{result.get('error_message', 'Unknown error')}"
    )


CITATION_LOOKUP_MAX_CHARS = 50_000


def verify_citations_in_text(text: str) -> list[dict[str, Any]]:
    """Resolve every citation in ``text`` against CourtListener in one request.

    Existence checking only: each result says whether the citation resolves to
    a real case, and to which. It says nothing about what the case holds or
    whether it is still good law.
    """
    text = text.strip()
    if not text:
        raise ValueError("no text to verify")
    if len(text) > CITATION_LOOKUP_MAX_CHARS:
        raise ValueError(
            f"text is {len(text)} characters; the citation-lookup limit is "
            f"{CITATION_LOOKUP_MAX_CHARS}. Split the document and verify in parts."
        )
    response = post(
        f"{API_BASE_URL}/citation-lookup/",
        headers=auth_headers(),
        data={"text": text},
        timeout=120,
    )
    results = []
    for item in response.json():
        status = item.get("status")
        clusters = item.get("clusters") or []
        if status == 200 and clusters:
            verdict = "found"
        elif status == 300:
            verdict = "ambiguous"
        elif status == 404 or (status == 200 and not clusters):
            verdict = "not_found"
        elif status == 429:
            verdict = "rate_limited"
        else:
            verdict = "invalid"
        matches = [
            {
                "case_name": c.get("case_name", ""),
                "date_filed": c.get("date_filed", ""),
                "url": f"{COURTLISTENER_BASE_URL}{c.get('absolute_url', '')}"
                if c.get("absolute_url")
                else "",
            }
            for c in clusters[:5]
        ]
        results.append(
            {
                "citation": item.get("citation", ""),
                "normalized": (item.get("normalized_citations") or [""])[0],
                "verdict": verdict,
                "matches": matches,
                **(
                    {"error": item.get("error_message")}
                    if item.get("error_message")
                    else {}
                ),
            }
        )
    return results


def fetch_cluster(cluster_id: int) -> dict:
    return get(f"{API_BASE_URL}/clusters/{cluster_id}/", headers=auth_headers()).json()


def fetch_opinion(opinion_id: int) -> dict:
    params = {"fields": "id,html_with_citations,plain_text,type,author_id"}
    return get(
        f"{API_BASE_URL}/opinions/{opinion_id}/",
        headers=auth_headers(),
        params=params,
    ).json()


def opinion_html_content(opinion: dict) -> str:
    html_content = opinion.get("html_with_citations") or ""
    if html_content:
        return html_content
    plain_text = opinion.get("plain_text") or ""
    if not plain_text:
        return ""
    return f"<pre>{escape(plain_text)}</pre>\n"


def opinion_markdown_content(opinion: dict) -> str:
    html_content = opinion.get("html_with_citations") or ""
    if html_content:
        return html_to_markdown(html_content)
    plain_text = opinion.get("plain_text") or ""
    if plain_text:
        text = plain_text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\f", "\n\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip() + "\n"
    return html_to_markdown("")


def fetch_docket(docket_id: int) -> dict:
    params = {"fields": "id,docket_number,court_id"}
    return get(
        f"{API_BASE_URL}/dockets/{docket_id}/",
        headers=auth_headers(),
        params=params,
    ).json()


def find_opinion_with_content(sub_opinions: list[str]) -> tuple[dict, str]:
    for opinion_url in sub_opinions:
        opinion_id = int(opinion_url.rstrip("/").split("/")[-1])
        opinion = fetch_opinion(opinion_id)
        html_content = opinion_html_content(opinion)
        if html_content:
            return opinion, html_content

    opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
    opinion = fetch_opinion(opinion_id)
    return opinion, ""


def build_citation_string(citation: dict) -> str | None:
    volume = citation.get("volume")
    reporter = citation.get("reporter")
    page = citation.get("page")
    if volume and reporter and page:
        return f"{volume} {reporter} {page}"
    return None


def _case_id(cluster_id: Any, absolute_url: str) -> str:
    """Build the on-disk directory name for a saved case.

    The slug comes from an API response and becomes a path segment, so it is
    sanitized rather than trusted.
    """
    parts = [part for part in absolute_url.split("/") if part]
    slug = parts[2] if len(parts) >= 3 and parts[0] == "opinion" else ""
    if slug:
        slug = sanitize_filename(slug, limit=80)
        if slug == "unnamed":
            slug = ""
    return f"cl-{cluster_id}-{slug}" if slug else f"cl-{cluster_id}"


def build_metadata(
    cluster: dict,
    opinion: dict,
    docket: dict | None = None,
    lookup_citation_value: str | None = None,
) -> dict[str, Any]:
    citations = [
        cite_str
        for citation in cluster.get("citations", [])
        if (cite_str := build_citation_string(citation))
    ]
    absolute_url = cluster.get("absolute_url", "")
    full_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else "N/A"
    court_id = docket.get("court_id", "unknown") if docket else "unknown"
    docket_number = docket.get("docket_number", "") if docket else ""
    cluster_id = cluster.get("id", "")
    # absolute_url is like "/opinion/5687761/winegrad-v-new-york-university-medical-center/"
    case_id = _case_id(cluster_id, absolute_url)
    return {
        "schema_version": 1,
        "id": case_id,
        "cluster_id": cluster_id,
        "opinion_id": opinion.get("id", ""),
        "source": "courtlistener",
        "case_name": cluster.get("case_name", "N/A"),
        "court": "",
        "court_id": court_id,
        "date_filed": cluster.get("date_filed", ""),
        "docket_number": docket_number,
        "citations": citations,
        "lookup_citation": lookup_citation_value or "",
        "precedential_status": cluster.get("precedential_status", ""),
        "source_url": full_url,
    }


def _markdownify_children(element) -> str:
    parts: list[str] = []
    for child in element.children:
        if isinstance(child, str):
            parts.append(child)
            continue

        text = _markdownify_element(child)
        if text:
            parts.append(text)

    text = "".join(parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return text.strip()


def _markdownify_element(element) -> str:
    name = getattr(element, "name", None)
    if not name:
        return ""

    if name == "page-number":
        label = element.get("label", "").strip()
        return f" [{label}] " if label else ""

    if name in {"author"}:
        return f"**{_markdownify_children(element)}**"

    if name in {"em", "i"}:
        return f"*{_markdownify_children(element)}*"

    if name in {"strong", "b"}:
        return f"**{_markdownify_children(element)}**"

    if name == "blockquote":
        inner = _markdownify_children(element)
        if not inner:
            return ""
        return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())

    if name == "footnotemark":
        mark = _markdownify_children(element) or element.get_text(strip=True)
        return f"[{mark}]"

    if name == "a":
        text = _markdownify_children(element)
        href = (element.get("href") or "").strip()
        if not text:
            return ""
        if not href:
            return text
        if href.startswith("/"):
            href = f"{COURTLISTENER_BASE_URL}{href}"
        return f"[{text}]({href})"

    if name in {"span", "p", "div", "footnote", "opinion"}:
        return _markdownify_children(element)

    return element.get_text(" ", strip=True)


def html_to_markdown(html_content: str) -> str:
    if not html_content:
        return "_No opinion text available._\n"

    soup = BeautifulSoup(html_content, "html.parser")
    opinion = soup.find("opinion") or soup

    lines: list[str] = []
    opinion_type = opinion.get("type") if hasattr(opinion, "get") else None
    if opinion_type:
        lines.append(f"# {opinion_type.title()} Opinion")
        lines.append("")

    for child in opinion.children:
        if isinstance(child, str):
            continue

        if child.name == "author":
            author = _markdownify_children(child)
            if author:
                lines.append(author)
                lines.append("")
            continue

        if child.name == "p":
            text = _markdownify_children(child)
            if text:
                lines.append(text)
                lines.append("")
            continue

        if child.name == "blockquote":
            quote = _markdownify_element(child)
            if quote:
                lines.append(quote)
                lines.append("")
            continue

        if child.name == "footnote":
            label = child.get("label", "").strip()
            body = _markdownify_children(child)
            if body:
                prefix = f"[^{label}]: " if label else "[^note]: "
                formatted = body.replace("\n", "\n  ")
                lines.append(prefix + formatted)
                lines.append("")
            continue

        text = _markdownify_element(child)
        if text:
            lines.append(text)
            lines.append("")

    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result + "\n"


def default_cases_dir() -> Path:
    return get_data_dir() / "cases"


def _complete_saved_case(case_dir: Path) -> bool:
    """A case is complete with both opinion files and either metadata format.

    ``metadata.yaml`` appears only in libraries written by the retired
    script-based skill; the connector writes ``metadata.json``.
    """
    if not all((case_dir / name).exists() for name in ("opinion.html", "opinion.md")):
        return False
    return (case_dir / "metadata.json").exists() or (case_dir / "metadata.yaml").exists()


def _saved_source(case_dir: Path) -> SavedSource:
    """Build a cached result from a saved case's metadata."""
    metadata = read_metadata(case_dir)
    return SavedSource(
        source_family="courtlistener",
        path=case_dir,
        source_url=str(metadata.get("source_url") or ""),
        description=str(metadata.get("case_name") or case_dir.name),
        status="already_saved",
    )


def find_saved_by_cluster_id(cluster_id: int, output_dir: Path | None = None) -> SavedSource | None:
    """Find a complete saved opinion without making a network request.

    Directory names are ``cl-{cluster_id}`` or ``cl-{cluster_id}-{slug}``. The
    glob must not be ``cl-{id}*``: cluster 123 would match ``cl-1234-...`` and
    silently return a different case.
    """
    directory = output_dir or default_cases_dir()
    if not directory.exists():
        return None
    candidates = [directory / f"cl-{cluster_id}", *directory.glob(f"cl-{cluster_id}-*")]
    for case_dir in candidates:
        if case_dir.is_dir() and _complete_saved_case(case_dir):
            return _saved_source(case_dir)
    return None


def _normalized_citation(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def read_metadata(case_dir: Path) -> dict[str, Any]:
    """Return a saved case's metadata.

    The connector writes ``metadata.json`` only. Libraries created by the
    retired script-based skill contain ``metadata.yaml`` instead; those fall
    back to a tolerant scan so an existing customer library keeps working.
    """
    json_path = case_dir / "metadata.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data
    return _legacy_metadata_from_yaml(case_dir / "metadata.yaml")


def _legacy_metadata_from_yaml(path: Path) -> dict[str, Any]:
    """Recover metadata from a pre-metadata.json library.

    Deliberately minimal: it only needs to carry the fields the cache and
    display paths use, for libraries written by an earlier version.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = {}
    citations: list[str] = []
    in_citations = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not raw_line.startswith((" ", "\t")):
            in_citations = stripped == "citations:"
            if ":" in stripped and not in_citations:
                key, _, value = stripped.partition(":")
                data[key.strip()] = value.strip().strip('"')
            continue
        if in_citations and stripped.startswith("- "):
            citations.append(stripped[2:].strip().strip('"'))
    data["citations"] = citations
    return data


def _saved_citations(case_dir: Path) -> set[str]:
    """Return the citations recorded for a saved case.

    Matching must be against these values alone. A substring search over the
    whole metadata file makes '5 F.3d 1' match a case reported at '5 F.3d 100',
    silently returning the wrong authority.
    """
    metadata = read_metadata(case_dir)
    values = list(metadata.get("citations") or [])
    if lookup := metadata.get("lookup_citation"):
        values.append(lookup)
    return {
        normalized for value in values if (normalized := _normalized_citation(str(value)))
    }


def find_saved_by_citation(citation: str, output_dir: Path | None = None) -> SavedSource | None:
    """Find a saved opinion whose recorded citations exactly match ``citation``."""
    directory = output_dir or default_cases_dir()
    if not directory.exists():
        return None
    needle = _normalized_citation(citation)
    if not needle:
        return None
    for case_dir in sorted(directory.glob("cl-*")):
        if not case_dir.is_dir() or not _complete_saved_case(case_dir):
            continue
        if needle in _saved_citations(case_dir):
            return _saved_source(case_dir)
    return None


def parse_search_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return {key: value[0] if len(value) == 1 else value for key, value in params.items()}


MAX_SEARCH_PAGES = 40


def search_opinions(
    params: dict[str, str],
    *,
    max_results: int | None = None,
    max_pages: int = MAX_SEARCH_PAGES,
) -> list[dict]:
    """Page through opinion search results, stopping as soon as it can.

    ``max_results`` bounds the walk itself rather than truncating afterwards.
    CourtListener is run by a nonprofit and paginating an entire result set to
    display or save a handful of cases wastes their capacity and the user's
    rate limit. ``max_pages`` is a backstop against a runaway ``next`` chain.
    """
    all_results: list[dict] = []
    url = f"{API_BASE_URL}/search/"
    page = 1

    while url:
        log(f"Fetching search results page {page}...")
        response = get(
            url,
            headers=auth_headers(),
            params=params if page == 1 else None,
        )
        data = response.json()
        results = data.get("results", [])
        all_results.extend(results)
        log(f"  Found {len(results)} results (total: {len(all_results)})")

        if max_results is not None and len(all_results) >= max_results:
            log(f"  Reached the requested maximum of {max_results}; stopping.")
            return all_results[:max_results]
        if page >= max_pages:
            log(
                f"  Stopping at the {max_pages}-page safety limit; "
                "narrow the query for complete coverage."
            )
            break

        url = data.get("next")
        params = None
        page += 1

    return all_results


def download_opinion_by_cluster_id(
    cluster_id: int,
    *,
    output_dir: Path | None = None,
    lookup_citation_value: str | None = None,
) -> SavedSource:
    cluster = fetch_cluster(cluster_id)
    case_name = cluster.get("case_name", "unknown")
    docket_id = cluster.get("docket_id")
    docket = fetch_docket(docket_id) if docket_id else None
    sub_opinions = cluster.get("sub_opinions", [])
    if not sub_opinions:
        raise ValueError(f"No opinions found in cluster {cluster_id}")

    opinion, html_content = find_opinion_with_content(sub_opinions)
    metadata = build_metadata(
        cluster,
        opinion,
        docket=docket,
        lookup_citation_value=lookup_citation_value,
    )
    directory = ensure_directory(output_dir or default_cases_dir())
    case_dir = ensure_directory(directory / str(metadata["id"]))
    html_path = case_dir / "opinion.html"
    opinion_path = case_dir / "opinion.md"
    opinion_markdown = opinion_markdown_content(opinion)
    write_text_atomic(html_path, html_content)
    write_text_atomic(opinion_path, opinion_markdown)
    # metadata.json is written last. _complete_saved_case checks the opinion
    # files and then metadata, so writing metadata last means a concurrent
    # reader never sees a case directory count as complete before the opinion
    # files it describes are fully on disk.
    write_text_atomic(
        case_dir / "metadata.json",
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
    )
    absolute_url = cluster.get("absolute_url", "")
    full_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else ""
    return SavedSource(
        source_family="courtlistener",
        path=case_dir,
        source_url=full_url,
        description=case_name,
    )


def fetch_by_url(
    url: str,
    *,
    output_dir: Path | None = None,
    refresh: bool = False,
) -> SavedSource:
    cluster_id = parse_opinion_url(url)
    if not refresh and (saved := find_saved_by_cluster_id(cluster_id, output_dir)):
        log(f"Using saved opinion: {saved.path}")
        return saved
    log(f"Fetching cluster {cluster_id}...")
    return download_opinion_by_cluster_id(
        cluster_id,
        output_dir=output_dir,
    )


def fetch_by_citation(
    citation: str,
    *,
    output_dir: Path | None = None,
    refresh: bool = False,
) -> SavedSource:
    if not refresh and (saved := find_saved_by_citation(citation, output_dir)):
        log(f"Using saved opinion: {saved.path}")
        return saved
    log(f"Looking up citation: {citation}")
    cluster_id = lookup_citation(citation)
    log(f"Found cluster {cluster_id}")
    if not refresh and (saved := find_saved_by_cluster_id(cluster_id, output_dir)):
        log(f"Using saved opinion: {saved.path}")
        return saved
    return download_opinion_by_cluster_id(
        cluster_id,
        output_dir=output_dir,
        lookup_citation_value=citation,
    )


def fetch_search_results(
    search_url: str,
    *,
    output_dir: Path | None = None,
    limit: int | None = None,
    skip_existing: bool = False,
) -> list[SavedSource]:
    params = parse_search_url(search_url)
    if params.get("type") != "o":
        log("Warning: Search type is not 'o' (opinions). Setting type=o.")
        params["type"] = "o"

    results = search_opinions(params, max_results=limit)
    directory = ensure_directory(output_dir or default_cases_dir())
    log(f"\nFound {len(results)} opinions to download into {directory}")
    saved: list[SavedSource] = []
    failed: list[tuple[int, str, str]] = []
    skipped_missing_cluster_id = 0
    skipped_existing = 0

    for index, result in enumerate(results, start=1):
        cluster_id = result.get("cluster_id")
        case_name = result.get("caseName", "unknown")
        if not cluster_id:
            skipped_missing_cluster_id += 1
            log(f"[{index}/{len(results)}] Skipping result without cluster_id: {case_name}")
            continue
        absolute_url = result.get("absolute_url", "")
        case_id = _case_id(cluster_id, absolute_url)
        case_dir = directory / str(case_id)
        if skip_existing and _complete_saved_case(case_dir):
            skipped_existing += 1
            log(f"[{index}/{len(results)}] Skipping existing: {case_name} -> {case_dir}")
            continue
        log(f"[{index}/{len(results)}] Downloading: {case_name} -> {case_dir}")
        try:
            saved_source = download_opinion_by_cluster_id(
                cluster_id,
                output_dir=directory,
            )
        except (HttpError, TimeoutError) as exc:
            failed.append((index, case_name, str(exc)))
            log(f"[{index}/{len(results)}] Failed: {case_name}: {exc}")
            continue
        saved.append(saved_source)
        log(f"[{index}/{len(results)}] Saved: {saved_source.path}")

    log(
        "\nDownload summary: "
        f"downloaded={len(saved)}, "
        f"skipped_existing={skipped_existing}, "
        f"skipped_missing_cluster_id={skipped_missing_cluster_id}, "
        f"failed={len(failed)}, "
        f"total_results={len(results)}"
    )
    if failed:
        log("Failed opinions:")
        for index, case_name, error in failed:
            log(f"  [{index}/{len(results)}] {case_name}: {error}")

    return saved
