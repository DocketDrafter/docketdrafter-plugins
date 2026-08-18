#!/usr/bin/env python3
"""Read and search the bundled Florida Statutes corpus.

Corpus layout (built by build_from_chapter_html.py):

  references/index.json              master law index
  references/aliases.json            citation-prefix → lawId
  references/laws/FS/law.json        law metadata
  references/laws/FS/index.json      sections + chapters + titles
  references/laws/FS/chapters/chapter-NNNN.html
                                     one HTML file per FS chapter
"""

from __future__ import annotations

import argparse
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
    """Extract the <pre> text inside a specific <article id=...>."""

    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.in_target = False
        self.in_pre = False
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag == "article" and amap.get("id") == self.target_id:
            self.in_target = True
            self.depth = 1
            return
        if self.in_target:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if not self.in_target:
            return
        if tag == "pre":
            self.in_pre = False
        self.depth -= 1
        if self.depth <= 0:
            self.in_target = False

    def handle_data(self, data: str) -> None:
        if self.in_target and self.in_pre:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


class AllSectionsExtractor(HTMLParser):
    """Extract every section's <pre> text from a chapter HTML file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cur: str | None = None
        self.in_pre = False
        self.depth = 0
        self.buf: list[str] = []
        self.results: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag == "article" and (amap.get("id") or "").startswith("section-"):
            self.cur = amap["id"]
            self.depth = 1
            self.buf = []
            return
        if self.cur:
            self.depth += 1
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if not self.cur:
            return
        if tag == "pre":
            self.in_pre = False
        self.depth -= 1
        if self.depth <= 0:
            self.results[self.cur] = "".join(self.buf)
            self.cur = None
            self.buf = []

    def handle_data(self, data: str) -> None:
        if self.cur and self.in_pre:
            self.buf.append(data)


REGEX_METACHARS = re.compile(r"[|\\^$+*?{}\[\]()]|\\b|\\d|\\s|\\w")


def default_root() -> Path:
    return ensure_corpus("fl-laws")


def fail(message: str) -> None:
    raise LookupErrorWithDetail(message)


def load_json(path: Path, *, purpose: str) -> Any:
    if not path.exists():
        fail(f"Missing {purpose}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON while reading {purpose}: {path}\n{exc}")


def normalize_section(section: str) -> str:
    return section.strip().removeprefix("§").strip().rstrip(".")


def parse_citation(citation: str) -> tuple[str, str]:
    s = citation.strip()
    s = re.sub(r"§+\s*", "", s)
    s = re.sub(r"\b(?:section|sec\.)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:florida statutes?|fla\.?\s*stat\.?(?:\s*ann\.?)?|f\.?s\.?a?\.?)", " FS ",
               s, flags=re.IGNORECASE)
    s = " ".join(s.split())

    if re.fullmatch(r"\d[\w.]*", s):
        return "FS", normalize_section(s)

    m = re.match(r"(?P<prefix>.+?)\s+(?P<section>\d[\w.]*?)\.?$", s)
    if not m:
        fail(
            f"Could not parse Florida Statutes citation: {citation!r}\n"
            "Expected forms: '1.015', 'FS 1.015', 'Fla. Stat. § 90.803'."
        )
    return m.group("prefix").strip(), normalize_section(m.group("section"))


def resolve_law_id(root: Path, prefix: str) -> str:
    aliases = load_json(root / "aliases.json", purpose="Florida aliases index")
    law_id = aliases.get(prefix) or aliases.get(prefix.upper()) or aliases.get(prefix.lower())
    if not law_id:
        fail(
            f"Unknown Florida law alias: {prefix!r}. Known aliases: "
            + ", ".join(sorted(aliases))
        )
    return law_id


def resolve(root: Path, citation: str) -> tuple[dict[str, Any], str, str]:
    prefix, section = parse_citation(citation)
    law_id = resolve_law_id(root, prefix)
    law_index = load_json(root / "laws" / law_id / "index.json",
                          purpose=f"Florida law index for {law_id}")
    sections = law_index.get("sections") or {}
    entry = sections.get(section)
    if not entry:
        sample = ", ".join(list(sections)[:20])
        fail(
            f"Florida Statutes section not found: {citation!r}\n"
            f"Parsed section: {section!r}\n"
            f"Sample section IDs: {sample}\n"
            "Try --list-chapter <chapter> or --search <keyword>."
        )
    html_path = root / "laws" / law_id / entry["path"]
    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    if not text and entry.get("textLength"):
        fail(f"Could not extract text for {citation!r}; expected anchor {entry['anchor']!r} in {html_path}")
    return entry, text, law_id


def status_banner(entry: dict[str, Any]) -> str:
    bits = []
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if entry.get("sourceUrl"):
        bits.append(entry["sourceUrl"])
    return " | ".join(bits)


def _size_tag(text_length: int | None) -> str:
    if not text_length:
        return ""
    if text_length >= 50_000:
        return f"  [~{text_length // 1000}KB !]"
    if text_length >= 20_000:
        return f"  [~{text_length // 1000}KB]"
    return ""


def print_section(entry: dict[str, Any], text: str, *, max_bytes: int | None = None) -> None:
    print(f"=== {entry['citation']} - {entry.get('title') or ''} [{status_banner(entry)}] ===")
    if max_bytes is not None and len(text) > max_bytes:
        print(text[:max_bytes])
        print(f"\n[... truncated {len(text) - max_bytes:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
    else:
        print(text)
    if entry.get("history"):
        print()
        print(f"History.—{entry['history']}")
    if entry.get("note"):
        print(f"Note.—{entry['note']}")


def cmd_list_laws(root: Path) -> int:
    index = load_json(root / "index.json", purpose="Florida master index")
    print("LAW  NAME              SECTIONS  ALIASES")
    for law_id, meta in sorted((index.get("laws") or {}).items()):
        aliases = ", ".join(meta.get("commonAliases") or [])
        print(f"{law_id:<4} {meta.get('name',''):<17} {meta.get('sectionCount', 0):>8}  {aliases}")
    return 0


def _load_law_index(root: Path) -> dict[str, Any]:
    return load_json(root / "laws" / "FS" / "index.json",
                     purpose="Florida Statutes index")


def cmd_list_chapter(root: Path, chapter: str) -> int:
    chapter = str(int(chapter))
    idx = _load_law_index(root)
    chapters = idx.get("chapters") or {}
    sections = idx.get("sections") or {}
    cmeta = chapters.get(chapter)
    if not cmeta:
        fail(f"No chapter {chapter} in corpus.")
    head = f"CHAPTER {chapter}"
    if cmeta.get("chapterName"):
        head += f" — {cmeta['chapterName']}"
    if cmeta.get("titleNumber"):
        head += f"  ({cmeta['titleNumber']}{': ' + cmeta['titleName'] if cmeta.get('titleName') else ''})"
    print(head)
    print(f"  {cmeta.get('sourceUrl','')}")
    print(f"  {cmeta.get('sectionCount',0)} sections")
    for sid in cmeta.get("sectionIds") or []:
        e = sections.get(sid) or {}
        print(f"  § {sid} — {e.get('title') or ''}{_size_tag(e.get('textLength'))}")
    return 0


def cmd_list_chapters(root: Path) -> int:
    idx = _load_law_index(root)
    chapters = idx.get("chapters") or {}
    print(f"FS — {len(chapters)} chapters")
    for chap in sorted(chapters, key=int):
        c = chapters[chap]
        print(f"  Ch. {chap:>4} — {c.get('chapterName','')}  [{c.get('sectionCount',0)} secs]")
    return 0


def _snippet(text: str, match: re.Match[str], width: int = 90) -> str:
    start, end = match.span()
    left = max(0, start - width)
    right = min(len(text), end + width)
    chunk = re.sub(r"\s+", " ", text[left:right]).strip()
    return f"{'...' if left else ''}{chunk}{'...' if right < len(text) else ''}"


def _scoped_sections(sections: dict[str, dict[str, Any]],
                     chapter: str | None) -> dict[str, dict[str, Any]]:
    if not chapter:
        return sections
    chapter = str(int(chapter))
    return {sid: e for sid, e in sections.items()
            if (e.get("chapter") or "") == chapter}


def cmd_search(
    root: Path,
    query: str,
    *,
    use_regex: bool,
    case_sensitive: bool,
    titles_only: bool,
    max_per_section: int,
    chapter: str | None,
) -> int:
    if not use_regex and REGEX_METACHARS.search(query):
        print(
            f"warning: pattern {query!r} contains regex metacharacters but "
            "--regex was not set; searching literally.",
            file=sys.stderr,
        )
    pattern = re.compile(
        query if use_regex else re.escape(query),
        0 if case_sensitive else re.IGNORECASE,
    )
    idx = _load_law_index(root)
    sections = _scoped_sections(idx.get("sections") or {}, chapter)
    total = 0

    if titles_only:
        for entry in sections.values():
            title = entry.get("title") or ""
            if pattern.search(title):
                print(f"{entry['citation']} — {title}{_size_tag(entry.get('textLength'))}")
                print(f"  {entry.get('sourceUrl') or ''}")
                total += 1
        if total == 0:
            print(f"No title matches for {query!r}.", file=sys.stderr)
            return 1
        return 0

    # Group sections by chapter file, load each file once.
    by_path: dict[str, list[dict[str, Any]]] = {}
    for entry in sections.values():
        by_path.setdefault(entry["path"], []).append(entry)
    laws_dir = root / "laws" / "FS"
    for path, entries in by_path.items():
        extractor = AllSectionsExtractor()
        extractor.feed((laws_dir / path).read_text(encoding="utf-8"))
        anchor_to_entry = {e["anchor"]: e for e in entries}
        for anchor, text in extractor.results.items():
            entry = anchor_to_entry.get(anchor)
            if not entry:
                continue
            matches = list(pattern.finditer(text))
            if not matches:
                continue
            print(f"{entry['citation']} — {entry.get('title') or ''}{_size_tag(entry.get('textLength'))}")
            print(f"  {entry.get('sourceUrl') or ''}")
            for m in matches[:max_per_section]:
                print(f"  {_snippet(text, m)}")
            if len(matches) > max_per_section:
                print(f"  (+{len(matches) - max_per_section} more match(es) in this section)")
            total += 1
    if total == 0:
        scope = f" chapter {chapter}" if chapter else " Florida Statutes"
        print(f"No matches for {query!r} in{scope}.", file=sys.stderr)
        return 1
    return 0


def cmd_read(root: Path, citations: list[str], fmt: str, max_bytes: int | None) -> int:
    for i, citation in enumerate(citations):
        entry, text, _ = resolve(root, citation)
        if fmt == "json":
            payload = dict(entry)
            payload["text"] = text
            payload["url"] = entry.get("sourceUrl")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        elif fmt == "markdown":
            print(f"# {entry['citation']} — {entry.get('title') or ''}")
            print()
            print(f"_{status_banner(entry)}_")
            print()
            print(text[:max_bytes] if max_bytes and len(text) > max_bytes else text)
            if entry.get("history"):
                print()
                print(f"_History.—{entry['history']}_")
            if entry.get("note"):
                print(f"_Note.—{entry['note']}_")
        else:
            if i:
                print()
            print_section(entry, text, max_bytes=max_bytes)
    return 0


def cmd_compare(root: Path, citations: list[str], max_bytes: int | None) -> int:
    if len(citations) < 2:
        fail("--compare requires at least two citations.")
    resolved = [resolve(root, c) for c in citations]
    print("Comparison summary")
    headers = ["citation", "title", "chars", "url"]
    rows = [
        [
            e["citation"],
            (e.get("title") or "")[:70],
            f"{e.get('textLength') or len(t):,}",
            e.get("sourceUrl") or "",
        ]
        for e, t, _ in resolved
    ]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))
    for entry, text, _ in resolved:
        print()
        print_section(entry, text, max_bytes=max_bytes)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read/search Florida Statutes from the bundled corpus.",
        epilog=(
            "Examples:\n"
            "  read_section.py '1.015'\n"
            "  read_section.py 'Fla. Stat. § 90.803' --max-bytes 5000\n"
            "  read_section.py --list-chapters\n"
            "  read_section.py --list-chapter 90\n"
            "  read_section.py --search hearsay --chapter 90\n"
            "  read_section.py --search insurance --titles-only\n"
            "  read_section.py --compare '90.803' '90.804'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*", help="One or more Florida Statutes citations.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--list-laws", action="store_true")
    parser.add_argument("--list-chapters", action="store_true",
                        help="List all chapters with names.")
    parser.add_argument("--list-chapter", metavar="CHAPTER",
                        help="List sections in one Florida Statutes chapter.")
    parser.add_argument("--search", metavar="QUERY", help="Search section text or titles.")
    parser.add_argument("--chapter", help="Restrict --search to a chapter number, e.g. 90.")
    parser.add_argument("--regex", action="store_true",
                        help="Treat --search as a regular expression.")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--titles-only", action="store_true",
                        help="With --search, match only catchline titles.")
    parser.add_argument("--max-per-section", type=int, default=2)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    try:
        if args.list_laws:
            sys.exit(cmd_list_laws(args.root))
        if args.list_chapters:
            sys.exit(cmd_list_chapters(args.root))
        if args.list_chapter:
            sys.exit(cmd_list_chapter(args.root, args.list_chapter))
        if args.search:
            sys.exit(cmd_search(
                args.root,
                args.search,
                use_regex=args.regex,
                case_sensitive=args.case_sensitive,
                titles_only=args.titles_only,
                max_per_section=args.max_per_section,
                chapter=args.chapter,
            ))
        if args.compare:
            sys.exit(cmd_compare(args.root, args.citations, args.max_bytes))
        if not args.citations:
            parser.error("provide citations, or use --list-laws / --list-chapters / "
                         "--list-chapter / --search / --compare")
        sys.exit(cmd_read(args.root, args.citations, args.format, args.max_bytes))
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
