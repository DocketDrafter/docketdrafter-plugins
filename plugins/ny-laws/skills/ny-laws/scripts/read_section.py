#!/usr/bin/env python3
"""Read a section from the bundled compact NY laws corpus."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from corpus import ensure_corpus
from typing import Any


class LookupErrorWithDetail(SystemExit):
    pass


class SectionTextExtractor(HTMLParser):
    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.in_target_article = False
        self.in_pre = False
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "article" and attr_map.get("id") == self.target_id:
            self.in_target_article = True
            self.depth = 1
            return
        if self.in_target_article:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if self.in_target_article and tag == "pre":
            self.in_pre = False
        if self.in_target_article:
            self.depth -= 1
            if self.depth <= 0:
                self.in_target_article = False

    def handle_data(self, data: str) -> None:
        if self.in_target_article and self.in_pre:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


class AllSectionsExtractor(HTMLParser):
    """Walk a sections.html file once and yield {anchor: text} for every <article>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_anchor: str | None = None
        self.in_pre = False
        self.depth = 0
        self.buf: list[str] = []
        self.results: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "article" and attr_map.get("id", "").startswith("section-"):
            self.current_anchor = attr_map["id"]
            self.depth = 1
            self.buf = []
            return
        if self.current_anchor is not None:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if self.current_anchor is None:
            return
        if tag == "pre":
            self.in_pre = False
        self.depth -= 1
        if self.depth <= 0:
            self.results[self.current_anchor] = "".join(self.buf)
            self.current_anchor = None
            self.buf = []

    def handle_data(self, data: str) -> None:
        if self.current_anchor is not None and self.in_pre:
            self.buf.append(data)


REGEX_METACHARS = re.compile(r"[|\\^$+*?{}\[\]()]|\\b|\\d|\\s|\\w")


def default_root() -> Path:
    return ensure_corpus("ny-laws")


def fail(message: str) -> None:
    raise LookupErrorWithDetail(message)


def load_json(path: Path, *, purpose: str) -> Any:
    if not path.exists():
        fail(
            f"Missing {purpose}: {path}\n"
            "Recovery: confirm the skill corpus was installed under the skill's references/ directory."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON while reading {purpose}: {path}\nJSON error: {exc}")


def parse_citation(citation: str) -> tuple[str, str]:
    normalized = " ".join(citation.strip().split())
    normalized = normalized.replace(" § ", " ").replace("§", "").strip()
    nyc_aliases = [
        "Administrative Code of the City of New York",
        "New York City Administrative Code",
        "NYC Administrative Code",
        "NYC Admin Code",
        "NYCAC",
    ]
    for alias in nyc_aliases:
        if normalized == alias:
            break
        prefix = f"{alias} "
        if normalized.lower().startswith(prefix.lower()):
            return normalized[: len(alias)], normalized[len(prefix) :].strip()
    match = re.match(r"(?P<prefix>.+?)\s+(?P<section>[0-9A-Za-z][0-9A-Za-z()._/-]*)$", normalized)
    if not match:
        fail(
            f"Could not parse NY citation: {citation!r}\n"
            "Expected shape: '<law prefix> <section>', for example 'CPLR 4518' or 'VTL 100'.\n"
            f"Normalized input: {normalized!r}"
        )
    return match.group("prefix"), match.group("section")


def resolve_law_id(root: Path, prefix: str) -> str:
    aliases_path = root / "aliases.json"
    aliases = load_json(aliases_path, purpose="NY aliases index")
    law_id = aliases.get(prefix) or aliases.get(prefix.upper())
    if not law_id:
        sample_aliases = ", ".join(sorted(list(aliases))[:20])
        suggestions = difflib.get_close_matches(prefix, aliases.keys(), n=5, cutoff=0.6)
        suggestion_text = (
            f"Did you mean: {', '.join(suggestions)}?\n"
            if suggestions
            else ""
        )
        fail(
            f"Unknown NY law alias: {prefix!r}\n"
            f"Aliases file checked: {aliases_path}\n"
            f"{suggestion_text}"
            f"Sample known aliases: {sample_aliases}\n"
            "Recovery: run with --list-laws, or inspect references/aliases.json."
        )
    return law_id


def resolve(root: Path, citation: str) -> tuple[dict[str, Any], str, str]:
    """Return (index entry, full section text, law_id)."""
    prefix, section = parse_citation(citation)
    if prefix.upper() in {"NYCRR", "22 NYCRR", "TITLE 22 NYCRR"}:
        if re.match(r"^(?:500|600|1250)\.", section):
            law_id = "NYCRR22"
        else:
            law_id = "NYUCS"
    else:
        law_id = resolve_law_id(root, prefix)

    index_path = root / "laws" / law_id / "index.json"
    law_index = load_json(index_path, purpose=f"NY law index for {law_id}")
    sections = law_index.get("sections") or {}
    entry = sections.get(section)
    if not entry:
        nearby = [key for key in sections if key.lower() == section.lower()]
        sample_sections = ", ".join(list(sections)[:20])
        fail(
            f"NY section not found while resolving citation: {citation!r}\n"
            f"Parsed prefix: {prefix!r}\n"
            f"Resolved lawId: {law_id!r}\n"
            f"Parsed section: {section!r}\n"
            f"Law index checked: {index_path}\n"
            f"Case-insensitive matches: {nearby or 'none'}\n"
            f"Sample section IDs: {sample_sections}\n"
            "Recovery: run with --list {law_id} to see all sections, or inspect the law index."
        )

    html_path = root / "laws" / law_id / entry["path"]
    if not html_path.exists():
        fail(
            f"NY section HTML file is missing for citation: {citation!r}\n"
            f"Resolved lawId: {law_id!r}\n"
            f"Index entry path: {entry['path']!r}\n"
            f"Expected HTML path: {html_path}\n"
            "Recovery: confirm references/laws/{lawId}/sections.html exists and the corpus copy is complete."
        )

    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    if not text and entry.get("textLength"):
        fail(
            f"Could not extract NY section text for citation: {citation!r}\n"
            f"Resolved lawId: {law_id!r}\n"
            f"Expected anchor: {entry['anchor']!r}\n"
            f"HTML path checked: {html_path}\n"
            "Recovery: search the HTML file for the anchor or inspect the section-start comments."
        )
    return entry, text, law_id


def public_url(law_id: str, doc_level_id: str, entry: dict[str, Any] | None = None) -> str:
    if entry and entry.get("sourceUrl"):
        return entry["sourceUrl"]
    return f"https://www.nysenate.gov/legislation/laws/{law_id}/{doc_level_id}"


def status_banner(entry: dict[str, Any], law_id: str | None = None) -> str:
    bits = [f"active: {entry.get('activeDate') or 'unknown'}"]
    if entry.get("repealed"):
        bits.append(f"REPEALED {entry.get('repealedDate') or ''}".strip())
    else:
        bits.append("not repealed")
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if law_id and (entry.get("docLevelId") or entry.get("sourceUrl")):
        bits.append(public_url(law_id, entry.get("docLevelId", ""), entry))
    return " | ".join(bits)


# ---------------------------------------------------------------------------
# Subsection slicing
# ---------------------------------------------------------------------------


def _find_subsection_boundaries(text: str) -> list[tuple[int, int, int]]:
    """Return [(subsection_number, start_offset, header_end_offset), ...].

    Detects NY's top-level subsection markers ("1. ", "2. ", ...). The first
    subsection often appears inline after the section title on the same line
    (e.g. "... retail places. 1. It shall be unlawful ..."); subsequent ones
    start at the beginning of a line preceded by indentation.
    """
    boundaries: list[tuple[int, int, int]] = []
    expected = 1
    # Require a sentence-ending period before the marker. This excludes
    # inline numbered lists (e.g., metes-and-bounds survey items inside
    # ABC § 101) which follow semicolons, not periods. The inline first
    # subsection after the section title also follows ". " so the same
    # rule covers it.
    pattern = re.compile(r"(?<=\.)\s+(\d{1,3})\.\s+(?=[A-Za-z\(])")
    for m in pattern.finditer(text):
        num = int(m.group(1))
        if num != expected:
            continue
        boundaries.append((num, m.start(), m.end()))
        expected += 1
    return boundaries


def _parse_subsection_spec(spec: str) -> set[int]:
    wanted: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            wanted.update(range(int(lo), int(hi) + 1))
        else:
            wanted.add(int(part))
    return wanted


def slice_subsections(text: str, spec: str) -> tuple[str, list[int], list[int]]:
    """Return (sliced_text, included, missing). Section header is preserved."""
    wanted = _parse_subsection_spec(spec)
    boundaries = _find_subsection_boundaries(text)
    if not boundaries:
        return text, [], sorted(wanted)
    # Header runs from start to first subsection start.
    header = text[: boundaries[0][1]].rstrip() + "\n"
    by_num = {num: (start, header_end) for num, start, header_end in boundaries}
    ends: dict[int, int] = {}
    for i, (num, start, _) in enumerate(boundaries):
        ends[num] = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(text)

    included: list[int] = []
    chunks: list[str] = [header]
    for num in sorted(wanted):
        if num not in by_num:
            continue
        start, _ = by_num[num]
        chunks.append(text[start : ends[num]].rstrip() + "\n")
        included.append(num)
    missing = sorted(n for n in wanted if n not in by_num)
    return "\n".join(chunks).rstrip() + "\n", included, missing


# ---------------------------------------------------------------------------


def print_section_text(
    entry: dict[str, Any],
    text: str,
    *,
    with_header: bool,
    law_id: str | None = None,
    max_bytes: int | None = None,
) -> None:
    if with_header:
        title = entry.get("title") or ""
        print(f"=== {entry['citation']} — {title} [{status_banner(entry, law_id)}] ===")
    if max_bytes is not None and len(text) > max_bytes:
        truncated = text[:max_bytes]
        print(truncated)
        omitted = len(text) - max_bytes
        print(f"\n[... truncated {omitted:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
    else:
        print(text)


def cmd_list_laws(root: Path) -> int:
    index = load_json(root / "index.json", purpose="NY master index")
    laws = index.get("laws") or {}
    rows = []
    for law_id, meta in sorted(laws.items()):
        aliases = ", ".join(meta.get("commonAliases") or [])
        rows.append((law_id, meta.get("name", ""), meta.get("sectionCount", 0), aliases))
    width_id = max(len(r[0]) for r in rows)
    width_name = max(len(r[1]) for r in rows)
    print(f"{'LAW'.ljust(width_id)}  {'NAME'.ljust(width_name)}  SECTIONS  ALIASES")
    for law_id, name, count, aliases in rows:
        print(f"{law_id.ljust(width_id)}  {name.ljust(width_name)}  {str(count).rjust(8)}  {aliases}")
    return 0


def _size_tag(text_length: int | None) -> str:
    if not text_length:
        return ""
    if text_length >= 50_000:
        return f"  [~{text_length // 1000}KB ⚠]"
    if text_length >= 20_000:
        return f"  [~{text_length // 1000}KB]"
    return ""


def cmd_list_sections(root: Path, prefix: str, article_filter: str | None) -> int:
    law_id = resolve_law_id(root, prefix)
    law_index = load_json(root / "laws" / law_id / "index.json", purpose=f"NY law index for {law_id}")
    sections = law_index.get("sections") or {}
    master = load_json(root / "index.json", purpose="NY master index")
    law_meta = (master.get("laws") or {}).get(law_id, {})
    print(f"{law_id} — {law_meta.get('name', '')} ({len(sections)} sections)")
    print()

    if law_id == "NYCAC":
        grouped_nyc: dict[tuple[str, str, str, str], list[tuple[str, dict[str, Any]]]] = {}
        order_nyc: list[tuple[str, str, str, str]] = []
        for section_id, entry in sections.items():
            key = (
                entry.get("titleNumber") or "",
                entry.get("titleTitle") or "",
                entry.get("chapter") or "",
                entry.get("chapterTitle") or "",
            )
            if key not in grouped_nyc:
                grouped_nyc[key] = []
                order_nyc.append(key)
            grouped_nyc[key].append((section_id, entry))
        if article_filter:
            order_nyc = [k for k in order_nyc if k[0] == article_filter or k[2] == article_filter]
            if not order_nyc:
                available = ", ".join(sorted({k[0] for k in grouped_nyc if k[0]}))
                fail(f"No sections found for NYCAC title/chapter {article_filter!r}.\nAvailable titles: {available}")
        for title_id, title_title, chapter_id, chapter_title in order_nyc:
            if title_id:
                header = f"Title {title_id}"
                if title_title:
                    header += f" — {title_title}"
            else:
                header = "Appendices"
            if chapter_id:
                header += f" / Chapter {chapter_id}"
                if chapter_title:
                    header += f" — {chapter_title}"
            print(header)
            for section_id, entry in grouped_nyc[(title_id, title_title, chapter_id, chapter_title)]:
                tag = " [REPEALED]" if entry.get("repealed") else ""
                title = entry.get("title") or ""
                size = _size_tag(entry.get("textLength"))
                print(f"  § {section_id} — {title}{tag}{size}")
            print()
        return 0

    grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    order: list[tuple[str, str]] = []
    for section_id, entry in sections.items():
        key = (entry.get("article") or "", entry.get("articleTitle") or "")
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((section_id, entry))

    if article_filter:
        order = [k for k in order if k[0] == article_filter]
        if not order:
            available = ", ".join(sorted({k[0] for k in grouped if k[0]}))
            fail(f"No sections found for article {article_filter!r} in {law_id}.\nAvailable articles: {available}")

    for article, article_title in order:
        header = f"Article {article}" if article else "(no article)"
        if article_title:
            header += f" — {article_title}"
        print(header)
        for section_id, entry in grouped[(article, article_title)]:
            tag = " [REPEALED]" if entry.get("repealed") else ""
            title = entry.get("title") or ""
            size = _size_tag(entry.get("textLength"))
            print(f"  § {section_id} — {title}{tag}{size}")
        print()
    return 0


def _law_ids_for_search(root: Path, scopes: list[str]) -> list[str]:
    if scopes:
        return [resolve_law_id(root, s) for s in scopes]
    master = load_json(root / "index.json", purpose="NY master index")
    return sorted((master.get("laws") or {}).keys())


def _snippet(text: str, match: re.Match[str], width: int = 80) -> str:
    start, end = match.span()
    left = max(0, start - width)
    right = min(len(text), end + width)
    chunk = text[left:right].replace("\n", " ")
    chunk = re.sub(r"\s+", " ", chunk).strip()
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{chunk}{suffix}"


def cmd_search(
    root: Path,
    query: str,
    scopes: list[str],
    *,
    use_regex: bool,
    case_sensitive: bool,
    titles_only: bool,
    max_per_section: int,
) -> int:
    if not use_regex and REGEX_METACHARS.search(query):
        print(
            f"warning: pattern {query!r} contains regex metacharacters but --regex was not set; "
            "searching as a literal string. Pass --regex to enable pattern matching.",
            file=sys.stderr,
        )
    pattern = re.compile(query if use_regex else re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    law_ids = _law_ids_for_search(root, scopes)
    total = 0
    for law_id in law_ids:
        law_index = load_json(root / "laws" / law_id / "index.json", purpose=f"NY law index for {law_id}")
        sections = law_index.get("sections") or {}

        if titles_only:
            for section_id, entry in sections.items():
                title = entry.get("title") or ""
                if pattern.search(title):
                    tag = " [REPEALED]" if entry.get("repealed") else ""
                    size = _size_tag(entry.get("textLength"))
                    print(f"{entry['citation']} — {title}{tag}{size}")
                    total += 1
            continue

        entries_by_path: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}
        for section_id, entry in sections.items():
            entries_by_path.setdefault(entry["path"], {})[entry["anchor"]] = (section_id, entry)

        for rel_path, anchor_to_entry in entries_by_path.items():
            html_path = root / "laws" / law_id / rel_path
            if not html_path.exists():
                continue
            extractor = AllSectionsExtractor()
            extractor.feed(html_path.read_text(encoding="utf-8"))

            for anchor, text in extractor.results.items():
                sid_entry = anchor_to_entry.get(anchor)
                if not sid_entry:
                    continue
                section_id, entry = sid_entry
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                tag = " [REPEALED]" if entry.get("repealed") else ""
                title = entry.get("title") or ""
                size = _size_tag(entry.get("textLength"))
                print(f"{entry['citation']} — {title}{tag}{size}")
                for m in matches[:max_per_section]:
                    print(f"  {_snippet(text, m)}")
                if len(matches) > max_per_section:
                    print(f"  (+{len(matches) - max_per_section} more match(es) in this section)")
                total += 1
    if total == 0:
        scope = ", ".join(law_ids)
        suffix = " (--titles-only matches section names only; rerun without it to search body text)" if titles_only else ""
        print(f"No matches for {query!r} in {scope}.{suffix}", file=sys.stderr)
        return 0
    return 0


def cmd_read_article(root: Path, spec: str, fmt: str, max_bytes: int | None) -> int:
    parts = spec.strip().split()
    if len(parts) != 2:
        fail(
            f"--read-article expects '<LAW> <article>', got: {spec!r}\n"
            "Example: --read-article 'CAN A4'"
        )
    prefix, article = parts
    law_id = resolve_law_id(root, prefix)
    law_index = load_json(root / "laws" / law_id / "index.json", purpose=f"NY law index for {law_id}")
    sections = law_index.get("sections") or {}
    matching = [entry["citation"] for entry in sections.values() if (entry.get("article") or "") == article]
    if not matching:
        available = sorted({entry.get("article") or "" for entry in sections.values() if entry.get("article")})
        fail(
            f"No sections found for article {article!r} in {law_id}.\n"
            f"Available articles: {', '.join(available)}"
        )
    return cmd_read(root, matching, fmt, subsections=None, max_bytes=max_bytes)


def cmd_read(
    root: Path,
    citations: list[str],
    fmt: str,
    *,
    subsections: str | None,
    max_bytes: int | None,
) -> int:
    multi = len(citations) > 1
    for i, citation in enumerate(citations):
        entry, text, law_id = resolve(root, citation)
        if subsections:
            sliced, included, missing = slice_subsections(text, subsections)
            if missing and included:
                print(
                    f"warning: requested subsection(s) {missing} not found in {entry['citation']}; "
                    f"included {included}.",
                    file=sys.stderr,
                )
            elif not included:
                print(
                    f"warning: no top-level subsection markers detected in {entry['citation']}; "
                    "printing full text.",
                    file=sys.stderr,
                )
            else:
                text = sliced
        if fmt == "json":
            payload = dict(entry)
            payload["text"] = text
            payload["url"] = public_url(law_id, entry.get("docLevelId", ""), entry)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        elif fmt == "markdown":
            print(f"# {entry['citation']} — {entry.get('title') or ''}")
            print()
            print(f"_{status_banner(entry, law_id)}_")
            print()
            if max_bytes is not None and len(text) > max_bytes:
                print(text[:max_bytes])
                print(f"\n[... truncated {len(text) - max_bytes:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
            else:
                print(text)
            if multi and i < len(citations) - 1:
                print("\n---\n")
        else:
            if multi and i > 0:
                print()
            # Single-citation calls now get a one-line banner above the text
            # so currency and source URL are always visible.
            print_section_text(entry, text, with_header=True, law_id=law_id, max_bytes=max_bytes)
    return 0


def cmd_compare(root: Path, citations: list[str], max_bytes: int | None) -> int:
    if len(citations) < 2:
        fail("--compare requires at least two citations.")
    resolved: list[tuple[dict[str, Any], str, str]] = [resolve(root, c) for c in citations]

    # Top summary table.
    print("Comparison summary")
    headers = ["citation", "title", "active", "repealed", "chars", "url"]
    rows = []
    for entry, text, law_id in resolved:
        rows.append([
            entry["citation"],
            (entry.get("title") or "")[:60],
            entry.get("activeDate") or "?",
            "yes" if entry.get("repealed") else "no",
            f"{entry.get('textLength') or len(text):,}",
            public_url(law_id, entry.get("docLevelId", ""), entry),
        ])
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt_row = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt_row.format(*headers))
    print(fmt_row.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt_row.format(*r))
    print()

    for entry, text, law_id in resolved:
        print()
        print_section_text(entry, text, with_header=True, law_id=law_id, max_bytes=max_bytes)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read a New York law section from the bundled skill corpus.",
        epilog=(
            "Examples:\n"
            "  read_section.py 'CPLR 4518'\n"
            "  read_section.py 'ABC 101' --subsections 1,2\n"
            "  read_section.py 'ABC 101' --max-bytes 8000\n"
            "  read_section.py --compare 'ABC 101' 'CAN 80'\n"
            "  read_section.py --list ABC --article A8\n"
            "  read_section.py --read-article 'CAN A4'\n"
            "  read_section.py --search 'twenty-one' CAN"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*", help="One or more citations, e.g. 'ABC 100'.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--list-laws", action="store_true", help="List every law in the corpus with its aliases.")
    parser.add_argument("--list", metavar="LAW", help="List all sections of LAW (by alias or lawId), grouped by article.")
    parser.add_argument("--article", help="With --list, restrict to a single article (e.g. A8).")
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Citation-aware search. Returns each matching section as 'LAW § — title' with snippets. "
             "Scope to specific laws by passing law aliases as positional args (otherwise searches all laws).",
    )
    parser.add_argument("--regex", action="store_true", help="With --search, treat QUERY as a regular expression.")
    parser.add_argument("--case-sensitive", action="store_true", help="With --search, match case-sensitively.")
    parser.add_argument("--titles-only", action="store_true", help="With --search, match only section titles.")
    parser.add_argument("--max-per-section", type=int, default=2, help="With --search, max snippets per section (default 2).")
    parser.add_argument(
        "--read-article",
        metavar="'LAW ART'",
        help="Read every section of an article in one call, e.g. --read-article 'CAN A4'.",
    )
    parser.add_argument(
        "--subsections",
        metavar="SPEC",
        help="When reading, return only listed top-level subsections. "
             "Examples: --subsections 1,2 or --subsections 1-3.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        help="Truncate each section's text at this many bytes, with a clear marker.",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare two or more citations side-by-side (summary table + each full section with banner).",
    )
    args = parser.parse_args()

    try:
        if args.list_laws:
            sys.exit(cmd_list_laws(args.root))
        if args.list:
            sys.exit(cmd_list_sections(args.root, args.list, args.article))
        if args.search:
            sys.exit(cmd_search(
                args.root,
                args.search,
                args.citations,
                use_regex=args.regex,
                case_sensitive=args.case_sensitive,
                titles_only=args.titles_only,
                max_per_section=args.max_per_section,
            ))
        if args.read_article:
            sys.exit(cmd_read_article(args.root, args.read_article, args.format, args.max_bytes))
        if args.compare:
            sys.exit(cmd_compare(args.root, args.citations, args.max_bytes))
        if not args.citations:
            parser.error("provide one or more citations, or use --list-laws / --list LAW / --search / --read-article / --compare")
        sys.exit(cmd_read(
            args.root,
            args.citations,
            args.format,
            subsections=args.subsections,
            max_bytes=args.max_bytes,
        ))
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
