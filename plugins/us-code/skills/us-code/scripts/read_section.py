#!/usr/bin/env python3
"""Read a section from the bundled compact U.S. Code corpus."""

from __future__ import annotations

import argparse
import json
import lzma
import re
import sys
from html.parser import HTMLParser
from urllib.parse import quote
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
    return ensure_corpus("us-code")


def fail(message: str) -> None:
    raise LookupErrorWithDetail(message)


def read_corpus_html(path: Path) -> str:
    """Read development HTML or an XZ-compressed release copy."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    compressed = path.with_suffix(path.suffix + ".xz")
    if compressed.exists():
        with lzma.open(compressed, "rt", encoding="utf-8") as stream:
            return stream.read()
    fail(f"Missing corpus HTML: {path} (or {compressed})")


def corpus_file_exists(path: Path) -> bool:
    return path.exists() or path.with_suffix(path.suffix + ".xz").exists()


def load_json(path: Path, *, purpose: str) -> Any:
    compressed = path.with_suffix(path.suffix + ".xz")
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        actual_path = path
    elif compressed.exists():
        with lzma.open(compressed, "rt", encoding="utf-8") as stream:
            raw = stream.read()
        actual_path = compressed
    else:
        fail(
            f"Missing {purpose}: {path} (or {compressed})\n"
            "Recovery: confirm the skill corpus was installed under the skill's references/ directory."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON while reading {purpose}: {actual_path}\nJSON error: {exc}")


def parse_citation(citation: str) -> tuple[str, str]:
    normalized = " ".join(citation.replace("§", " ").strip().split())
    patterns = [
        r"^(?P<title>\d+)(?P<app_a>\s+App\.?)?\s+(?:U\.?S\.?C\.?)?\s*(?P<section>[0-9A-Za-z][0-9A-Za-z()._-]*)$",
        r"^(?P<title>\d+)\s+(?:U\.?S\.?C\.?)?\s+(?P<app_b>App\.?)\s*(?P<section>[0-9A-Za-z][0-9A-Za-z()._-]*)$",
    ]
    match = None
    for pattern in patterns:
        match = re.match(pattern, normalized, re.IGNORECASE)
        if match:
            break
    if not match:
        fail(
            f"Could not parse U.S. Code citation: {citation!r}\n"
            "Expected shapes include '42 U.S.C. § 1983', '42 USC 1983', or '18 App. U.S.C. § 1'.\n"
            f"Normalized input: {normalized!r}"
        )

    title = match.group("title")
    is_appendix = bool((match.groupdict().get("app_a") or match.groupdict().get("app_b")))
    title_key = f"{int(title)}-app" if is_appendix else str(int(title))
    return title_key, match.group("section")


def parse_title_key(token: str) -> str:
    """Accept '42', '42-app', '18 App', '18App.' etc. and return the canonical title key."""
    normalized = " ".join(token.replace("§", " ").strip().split())
    m = re.match(r"^(?P<title>\d+)(?:\s*(?P<app>App\.?|-app))?$", normalized, re.IGNORECASE)
    if not m:
        fail(f"Could not parse title key: {token!r}. Expected forms like '42', '18-app', or '18 App.'")
    title = str(int(m.group("title")))
    return f"{title}-app" if m.group("app") else title


def resolve(root: Path, citation: str) -> tuple[dict[str, Any], str, str]:
    """Return (index entry, full section text, title_key)."""
    title_key, section = parse_citation(citation)
    index_path = root / "titles" / title_key / "index.json"
    if not corpus_file_exists(index_path):
        titles_index_path = root / "index.json"
        titles_index = load_json(titles_index_path, purpose="U.S. Code title index")
        known_titles = ", ".join(
            sorted(titles_index.get("titles", {}).keys(), key=lambda key: (key.endswith("-app"), key))[:80]
        )
        fail(
            f"U.S. Code title folder not found while resolving citation: {citation!r}\n"
            f"Parsed title key: {title_key!r}\n"
            f"Expected title index: {index_path}\n"
            f"Known title keys include: {known_titles}\n"
            "Recovery: if this is an appendix citation, include 'App.' in the citation; otherwise inspect references/index.json."
        )

    title_index = load_json(index_path, purpose=f"U.S. Code title index for {title_key}")
    sections = title_index.get("sections") or {}
    entry = sections.get(section)
    if not entry:
        nearby = [key for key in sections if key.lower() == section.lower()]
        sample_sections = ", ".join(list(sections)[:30])
        fail(
            f"U.S. Code section not found while resolving citation: {citation!r}\n"
            f"Parsed title key: {title_key!r}\n"
            f"Parsed section: {section!r}\n"
            f"Title index checked: {index_path}\n"
            f"Case-insensitive matches: {nearby or 'none'}\n"
            f"Sample section IDs: {sample_sections}\n"
            "Recovery: inspect the title index's sections object for the exact section key, or run --list <title>."
        )

    html_path = root / "titles" / title_key / entry["path"]
    compressed_path = html_path.with_suffix(html_path.suffix + ".xz")
    if not html_path.exists() and not compressed_path.exists():
        fail(
            f"U.S. Code section HTML file is missing for citation: {citation!r}\n"
            f"Parsed title key: {title_key!r}\n"
            f"Index entry path: {entry['path']!r}\n"
            f"Expected HTML path: {html_path} (or {compressed_path})\n"
            "Recovery: confirm the title's sections.html or sections.html.xz file exists and the corpus copy is complete."
        )

    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(read_corpus_html(html_path))
    text = parser.text()
    if not text and entry.get("textLength"):
        fail(
            f"Could not extract U.S. Code section text for citation: {citation!r}\n"
            f"Parsed title key: {title_key!r}\n"
            f"Expected anchor: {entry['anchor']!r}\n"
            f"HTML path checked: {html_path}\n"
            "Recovery: search the HTML file for the anchor or inspect the section-start comments."
        )
    return entry, text, title_key


def official_url(title_key: str, section: str) -> str:
    """Return the official OLRC preliminary-edition section page."""
    if title_key.endswith("-app"):
        title = f"{title_key[:-4]}a"
        query = quote(f"title:{title} section:{section} edition:prelim", safe="")
        return f"https://uscode.house.gov/view.xhtml?req={query}&num=0&edition=prelim"
    if not re.fullmatch(r"[0-9A-Za-z-]+", section):
        # OLRC has no section granule for grouped ranges such as "1a–7b".
        return f"https://uscode.house.gov/download/download.shtml#us/usc/t{title_key}"
    granule = quote(f"USC-prelim-title{title_key}-section{section}", safe="")
    return f"https://uscode.house.gov/view.xhtml?req=granuleid:{granule}&num=0&edition=prelim"


def cornell_url(title_key: str, section: str) -> str:
    """Return the corresponding Cornell LII section page."""
    title = f"{title_key[:-4]}a" if title_key.endswith("-app") else title_key
    normalized = section.replace("–", "-")
    return f"https://www.law.cornell.edu/uscode/text/{title}/{quote(normalized, safe='-')}"


def public_url(title_key: str, section: str) -> str:
    """Backward-compatible alias for the official primary-source URL."""
    return official_url(title_key, section)


def status_banner(entry: dict[str, Any], title_key: str | None = None) -> str:
    bits = [f"current through: {entry.get('lawsEnactedThrough') or entry.get('currentThrough') or 'unknown'}"]
    if entry.get("isPlaceholder"):
        bits.append("PLACEHOLDER (no text / repealed / omitted)")
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if title_key and entry.get("section"):
        section = entry["section"]
        bits.append(f"OLRC: {official_url(title_key, section)}")
        bits.append(f"Cornell: {cornell_url(title_key, section)}")
    return " | ".join(bits)


# ---------------------------------------------------------------------------
# Chapter/part parsing from expcite
# ---------------------------------------------------------------------------


def _expcite_parts(entry: dict[str, Any]) -> dict[str, str]:
    """Parse expcite into {'part': ..., 'chapter': ..., 'subchapter': ...} segments."""
    expcite = entry.get("expcite") or ""
    out: dict[str, str] = {}
    for seg in expcite.split("!@!"):
        seg = seg.strip()
        if seg.startswith("PART "):
            out["part"] = seg[len("PART "):]
        elif seg.startswith("CHAPTER "):
            out["chapter"] = seg[len("CHAPTER "):]
        elif seg.startswith("SUBCHAPTER "):
            out["subchapter"] = seg[len("SUBCHAPTER "):]
    return out


def _chapter_number(entry: dict[str, Any]) -> str:
    """Return just the chapter number/identifier, e.g. '1' from 'CHAPTER 1-GENERAL PROVISIONS'."""
    chapter = _expcite_parts(entry).get("chapter", "")
    if not chapter:
        return ""
    # 'CHAPTER 1-GENERAL PROVISIONS' was stripped of 'CHAPTER ' already; split on '-' once.
    return chapter.split("-", 1)[0].strip()


def _chapter_title(entry: dict[str, Any]) -> str:
    chapter = _expcite_parts(entry).get("chapter", "")
    if "-" in chapter:
        return chapter.split("-", 1)[1].strip()
    return ""


# ---------------------------------------------------------------------------
# Subsection slicing
# ---------------------------------------------------------------------------


def _find_subsection_boundaries(text: str) -> tuple[str, list[tuple[str, int, int]]]:
    """Detect top-level subsection markers.

    USC top-level subsections are typically '(a)', '(b)', ... at the start of a line.
    Some sections use '(1)', '(2)', ... instead. Falls back gracefully if neither pattern
    is found.

    Returns ('letter' | 'number' | '', [(marker, start_offset, header_end_offset), ...]).
    """
    def collect(pattern: str, sequence: list[str]) -> list[tuple[str, int, int]]:
        boundaries: list[tuple[str, int, int]] = []
        expected_idx = 0
        for m in re.finditer(pattern, text, flags=re.MULTILINE):
            marker = m.group(1)
            if expected_idx < len(sequence) and marker == sequence[expected_idx]:
                boundaries.append((marker, m.start(), m.end()))
                expected_idx += 1
        return boundaries

    letters = [chr(c) for c in range(ord("a"), ord("z") + 1)]
    numbers = [str(n) for n in range(1, 100)]

    # Letter pattern: (a) at line start, possibly after some leading spaces, followed by space/text.
    letter_boundaries = collect(r"^\s*\(([a-z])\)\s+(?=\S)", letters)
    if len(letter_boundaries) >= 2:
        return "letter", letter_boundaries

    number_boundaries = collect(r"^\s*\((\d+)\)\s+(?=\S)", numbers)
    if len(number_boundaries) >= 2:
        return "number", number_boundaries

    # Fall back to NY-style "1. " markers preceded by a sentence-ending period.
    ny_pattern = re.compile(r"(?<=\.)\s+(\d{1,3})\.\s+(?=[A-Za-z\(])")
    expected = 1
    ny_boundaries: list[tuple[str, int, int]] = []
    for m in ny_pattern.finditer(text):
        num = int(m.group(1))
        if num != expected:
            continue
        ny_boundaries.append((str(num), m.start(), m.end()))
        expected += 1
    if len(ny_boundaries) >= 2:
        return "number", ny_boundaries
    return "", []


def _parse_subsection_spec(spec: str, kind: str) -> list[str]:
    """Parse '1,2', '1-3', 'a,c', or 'a-d' into an ordered list of marker strings."""
    wanted: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and len(part) > 1:
            lo, hi = part.split("-", 1)
            lo, hi = lo.strip(), hi.strip()
            if kind == "letter" or (lo.isalpha() and hi.isalpha()):
                for c in range(ord(lo), ord(hi) + 1):
                    wanted.append(chr(c))
            else:
                for n in range(int(lo), int(hi) + 1):
                    wanted.append(str(n))
        else:
            wanted.append(part)
    return wanted


def slice_subsections(text: str, spec: str) -> tuple[str, list[str], list[str]]:
    """Return (sliced_text, included, missing). Section header is preserved."""
    kind, boundaries = _find_subsection_boundaries(text)
    if not boundaries:
        # Caller will decide what to do; signal "nothing detected".
        return text, [], [s.strip() for s in spec.split(",") if s.strip()]
    wanted = _parse_subsection_spec(spec, kind)
    header = text[: boundaries[0][1]].rstrip() + "\n"
    by_marker = {marker: (start, hdr_end) for marker, start, hdr_end in boundaries}
    ends: dict[str, int] = {}
    for i, (marker, start, _) in enumerate(boundaries):
        ends[marker] = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(text)

    included: list[str] = []
    chunks: list[str] = [header]
    for marker in wanted:
        if marker not in by_marker:
            continue
        start, _ = by_marker[marker]
        chunks.append(text[start : ends[marker]].rstrip() + "\n")
        included.append(marker)
    missing = [m for m in wanted if m not in by_marker]
    return "\n".join(chunks).rstrip() + "\n", included, missing


# ---------------------------------------------------------------------------


def print_section_text(
    entry: dict[str, Any],
    text: str,
    *,
    with_header: bool,
    title_key: str | None = None,
    max_bytes: int | None = None,
) -> None:
    if with_header:
        heading = entry.get("heading") or ""
        print(f"=== {entry['citation']} — {heading} [{status_banner(entry, title_key)}] ===")
    if max_bytes is not None and len(text) > max_bytes:
        truncated = text[:max_bytes]
        print(truncated)
        omitted = len(text) - max_bytes
        print(f"\n[... truncated {omitted:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
    else:
        print(text)


def _size_tag(text_length: int | None) -> str:
    if not text_length:
        return ""
    if text_length >= 50_000:
        return f"  [~{text_length // 1000}KB ⚠]"
    if text_length >= 20_000:
        return f"  [~{text_length // 1000}KB]"
    return ""


def cmd_list_titles(root: Path) -> int:
    index = load_json(root / "index.json", purpose="U.S. Code master index")
    titles = index.get("titles") or {}
    rows = []
    for key in sorted(titles.keys(), key=lambda k: (k.endswith("-app"), int(k.split("-")[0]))):
        meta = titles[key]
        rows.append((key, meta.get("name", ""), meta.get("sectionCount", 0), meta.get("status", "")))
    width_id = max(len(r[0]) for r in rows)
    width_name = max(len(r[1]) for r in rows)
    print(f"{'TITLE'.ljust(width_id)}  {'NAME'.ljust(width_name)}  SECTIONS  STATUS")
    for key, name, count, status in rows:
        print(f"{key.ljust(width_id)}  {name.ljust(width_name)}  {str(count).rjust(8)}  {status}")
    return 0


def cmd_list_sections(root: Path, title_token: str, chapter_filter: str | None) -> int:
    title_key = parse_title_key(title_token)
    index_path = root / "titles" / title_key / "index.json"
    title_index = load_json(index_path, purpose=f"U.S. Code title index for {title_key}")
    sections = title_index.get("sections") or {}
    master = load_json(root / "index.json", purpose="U.S. Code master index")
    title_meta = (master.get("titles") or {}).get(title_key, {})
    print(f"Title {title_key} — {title_meta.get('name', '')} ({len(sections)} sections)")
    print()

    grouped: dict[tuple[str, str, str], list[tuple[str, dict[str, Any]]]] = {}
    order: list[tuple[str, str, str]] = []
    for section_id, entry in sections.items():
        parts = _expcite_parts(entry)
        key = (parts.get("part", ""), _chapter_number(entry), _chapter_title(entry))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((section_id, entry))

    if chapter_filter:
        order = [k for k in order if k[1] == chapter_filter]
        if not order:
            available = ", ".join(sorted({k[1] for k in grouped if k[1]}, key=lambda s: (len(s), s)))
            fail(f"No sections found for chapter {chapter_filter!r} in title {title_key}.\nAvailable chapters: {available}")

    for part, chapter_num, chapter_title in order:
        header_bits = []
        if part:
            header_bits.append(f"Part {part}")
        if chapter_num:
            ch = f"Chapter {chapter_num}"
            if chapter_title:
                ch += f" — {chapter_title}"
            header_bits.append(ch)
        header = " · ".join(header_bits) if header_bits else "(no chapter)"
        print(header)
        for section_id, entry in grouped[(part, chapter_num, chapter_title)]:
            heading = entry.get("heading") or ""
            tag = " [PLACEHOLDER]" if entry.get("isPlaceholder") else ""
            size = _size_tag(entry.get("textLength"))
            print(f"  § {section_id} — {heading}{tag}{size}")
        print()
    return 0


def _title_keys_for_search(root: Path, scopes: list[str]) -> list[str]:
    if scopes:
        return [parse_title_key(s) for s in scopes]
    master = load_json(root / "index.json", purpose="U.S. Code master index")
    titles = master.get("titles") or {}
    return sorted(titles.keys(), key=lambda k: (k.endswith("-app"), int(k.split("-")[0])))


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
    headings_only: bool,
    max_per_section: int,
) -> int:
    if not use_regex and REGEX_METACHARS.search(query):
        print(
            f"warning: pattern {query!r} contains regex metacharacters but --regex was not set; "
            "searching as a literal string. Pass --regex to enable pattern matching.",
            file=sys.stderr,
        )
    pattern = re.compile(query if use_regex else re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    title_keys = _title_keys_for_search(root, scopes)
    total = 0
    heading_zero_but_body_possible = False
    for title_key in title_keys:
        index_path = root / "titles" / title_key / "index.json"
        if not corpus_file_exists(index_path):
            continue
        title_index = load_json(index_path, purpose=f"U.S. Code title index for {title_key}")
        sections = title_index.get("sections") or {}

        if headings_only:
            for section_id, entry in sections.items():
                heading = entry.get("heading") or ""
                if pattern.search(heading):
                    tag = " [PLACEHOLDER]" if entry.get("isPlaceholder") else ""
                    size = _size_tag(entry.get("textLength"))
                    print(f"{entry['citation']} — {heading}{tag}{size}")
                    total += 1
            continue

        html_path = root / "titles" / title_key / "sections.html"
        compressed_path = html_path.with_suffix(html_path.suffix + ".xz")
        if not html_path.exists() and not compressed_path.exists():
            continue
        extractor = AllSectionsExtractor()
        extractor.feed(read_corpus_html(html_path))

        anchor_to_entry = {entry["anchor"]: (sid, entry) for sid, entry in sections.items()}
        for anchor, text in extractor.results.items():
            sid_entry = anchor_to_entry.get(anchor)
            if not sid_entry:
                continue
            section_id, entry = sid_entry
            matches = list(pattern.finditer(text))
            if not matches:
                continue
            tag = " [PLACEHOLDER]" if entry.get("isPlaceholder") else ""
            heading = entry.get("heading") or ""
            size = _size_tag(entry.get("textLength"))
            print(f"{entry['citation']} — {heading}{tag}{size}")
            for m in matches[:max_per_section]:
                print(f"  {_snippet(text, m)}")
            if len(matches) > max_per_section:
                print(f"  (+{len(matches) - max_per_section} more match(es) in this section)")
            total += 1
    if total == 0:
        scope_label = ", ".join(title_keys) if scopes else f"all {len(title_keys)} titles"
        hint = ""
        if headings_only:
            hint = " (--headings-only matches section names only; rerun without it to search body text)"
        print(f"No matches for {query!r} in {scope_label}.{hint}")
        return 0
    return 0


def cmd_read_chapter(root: Path, spec: str, fmt: str, max_bytes: int | None) -> int:
    parts = spec.strip().split()
    if len(parts) != 2:
        fail(
            f"--read-chapter expects '<TITLE> <chapter>', got: {spec!r}\n"
            "Example: --read-chapter '18 1'"
        )
    title_token, chapter = parts
    title_key = parse_title_key(title_token)
    index_path = root / "titles" / title_key / "index.json"
    title_index = load_json(index_path, purpose=f"U.S. Code title index for {title_key}")
    sections = title_index.get("sections") or {}
    matching = [entry["citation"] for entry in sections.values() if _chapter_number(entry) == chapter]
    if not matching:
        available = sorted({_chapter_number(entry) for entry in sections.values() if _chapter_number(entry)},
                           key=lambda s: (len(s), s))
        fail(
            f"No sections found for chapter {chapter!r} in title {title_key}.\n"
            f"Available chapters: {', '.join(available)}"
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
        entry, text, title_key = resolve(root, citation)
        if subsections:
            sliced, included, missing = slice_subsections(text, subsections)
            if not included and missing:
                print(
                    f"warning: no top-level subsection markers detected in {entry['citation']}; "
                    "printing full text.",
                    file=sys.stderr,
                )
            elif missing and included:
                print(
                    f"warning: requested subsection(s) {missing} not found in {entry['citation']}; "
                    f"included {included}.",
                    file=sys.stderr,
                )
                text = sliced
            elif included:
                text = sliced
        if fmt == "json":
            payload = dict(entry)
            payload["text"] = text
            section = entry.get("section", "")
            payload["url"] = official_url(title_key, section)
            payload["officialUrl"] = official_url(title_key, section)
            payload["cornellUrl"] = cornell_url(title_key, section)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        elif fmt == "markdown":
            print(f"# {entry['citation']} — {entry.get('heading') or ''}")
            print()
            print(f"_{status_banner(entry, title_key)}_")
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
            print_section_text(entry, text, with_header=True, title_key=title_key, max_bytes=max_bytes)
    return 0


def cmd_compare(root: Path, citations: list[str], max_bytes: int | None) -> int:
    if len(citations) < 2:
        fail("--compare requires at least two citations.")
    resolved: list[tuple[dict[str, Any], str, str]] = [resolve(root, c) for c in citations]

    print("Comparison summary")
    headers = ["citation", "heading", "current through", "placeholder", "chars", "OLRC", "Cornell"]
    rows = []
    for entry, text, title_key in resolved:
        rows.append([
            entry["citation"],
            (entry.get("heading") or "")[:60],
            entry.get("lawsEnactedThrough") or entry.get("currentThrough") or "?",
            "yes" if entry.get("isPlaceholder") else "no",
            f"{entry.get('textLength') or len(text):,}",
            official_url(title_key, entry.get("section", "")),
            cornell_url(title_key, entry.get("section", "")),
        ])
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt_row = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt_row.format(*headers))
    print(fmt_row.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt_row.format(*r))
    print()

    for entry, text, title_key in resolved:
        print()
        print_section_text(entry, text, with_header=True, title_key=title_key, max_bytes=max_bytes)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read a U.S. Code section from the bundled skill corpus.",
        epilog=(
            "Examples:\n"
            "  read_section.py '42 USC 1983'\n"
            "  read_section.py '18 USC 1962' --subsections a,b\n"
            "  read_section.py '42 USC 1983' --max-bytes 4000\n"
            "  read_section.py --compare '42 USC 1983' '42 USC 1985'\n"
            "  read_section.py --list 18 --chapter 96\n"
            "  read_section.py --read-chapter '18 96'\n"
            "  read_section.py --search 'racketeering' 18\n"
            "  read_section.py --list-titles"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*", help="One or more citations, e.g. '42 USC 1983'.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--list-titles", action="store_true", help="List every title in the corpus.")
    parser.add_argument("--list", metavar="TITLE", help="List all sections of TITLE (e.g. '18' or '18-app'), grouped by chapter.")
    parser.add_argument("--chapter", help="With --list or --read-chapter, restrict to one chapter (e.g. '96').")
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Citation-aware search. Returns each matching section as 'TITLE USC § — heading' with snippets. "
             "Scope by passing title numbers as positional args (otherwise searches every title).",
    )
    parser.add_argument("--regex", action="store_true", help="With --search, treat QUERY as a regular expression.")
    parser.add_argument("--case-sensitive", action="store_true", help="With --search, match case-sensitively.")
    parser.add_argument(
        "--headings-only",
        action="store_true",
        help="With --search, match only section headings (not body text). "
             "If zero matches, the script will hint to retry without this flag.",
    )
    parser.add_argument("--max-per-section", type=int, default=2, help="With --search, max snippets per section (default 2).")
    parser.add_argument(
        "--read-chapter",
        metavar="'TITLE CH'",
        help="Read every section of one chapter in a single call, e.g. --read-chapter '18 96'.",
    )
    parser.add_argument(
        "--subsections",
        metavar="SPEC",
        help="When reading, return only listed top-level subsections. "
             "USC uses (a),(b),(c) most often; some use (1),(2). "
             "Examples: --subsections a,b or --subsections a-c or --subsections 1,2.",
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
        if args.list_titles:
            sys.exit(cmd_list_titles(args.root))
        if args.list:
            sys.exit(cmd_list_sections(args.root, args.list, args.chapter))
        if args.search:
            sys.exit(cmd_search(
                args.root,
                args.search,
                args.citations,
                use_regex=args.regex,
                case_sensitive=args.case_sensitive,
                headings_only=args.headings_only,
                max_per_section=args.max_per_section,
            ))
        if args.read_chapter:
            sys.exit(cmd_read_chapter(args.root, args.read_chapter, args.format, args.max_bytes))
        if args.compare:
            sys.exit(cmd_compare(args.root, args.citations, args.max_bytes))
        if not args.citations:
            parser.error("provide one or more citations, or use --list-titles / --list TITLE / --search / --read-chapter / --compare")
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
