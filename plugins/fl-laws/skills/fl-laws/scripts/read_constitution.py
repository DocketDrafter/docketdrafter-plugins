#!/usr/bin/env python3
"""Read and search the bundled Florida Constitution corpus."""

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


ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
INT_TO_ROMAN = {
    1: "I",
    2: "II",
    3: "III",
    4: "IV",
    5: "V",
    6: "VI",
    7: "VII",
    8: "VIII",
    9: "IX",
    10: "X",
    11: "XI",
    12: "XII",
}
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


def roman_to_int(value: str) -> int | None:
    value = value.upper()
    total = 0
    prev = 0
    for ch in reversed(value):
        cur = ROMAN_VALUES.get(ch)
        if not cur:
            return None
        if cur < prev:
            total -= cur
        else:
            total += cur
            prev = cur
    return total


def normalize_article(value: str) -> str:
    value = value.strip().upper()
    if value.isdigit():
        roman = INT_TO_ROMAN.get(int(value))
        if roman:
            return roman
    num = roman_to_int(value)
    if num and num in INT_TO_ROMAN:
        return INT_TO_ROMAN[num]
    fail(f"Unknown Florida Constitution article: {value!r}")


def parse_citation(citation: str) -> str:
    s = citation.strip()
    s = re.sub(r"fla\.?\s*const\.?|florida\s+constitution|flconst", " ", s, flags=re.I)
    s = re.sub(r"§+", " section ", s)
    s = re.sub(r"\bart(?:icle)?\.?\b", " article ", s, flags=re.I)
    s = re.sub(r"\bsec(?:tion)?\.?\b", " section ", s, flags=re.I)
    s = s.replace(",", " ")
    s = " ".join(s.split())

    patterns = [
        r"article\s+(?P<article>[IVXLCDM]+|\d+)\s+section\s+(?P<section>\d+)",
        r"(?P<article>[IVXLCDM]+|\d+)\s+section\s+(?P<section>\d+)",
        r"(?P<article>[IVXLCDM]+|\d+)\.(?P<section>\d+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, s, flags=re.I)
        if m:
            article = normalize_article(m.group("article"))
            return f"{article}.{int(m.group('section'))}"
    fail(
        f"Could not parse Florida Constitution citation: {citation!r}\n"
        "Expected forms: 'Fla. Const. art. I, § 1', 'Article I section 1', or 'I.1'."
    )


def load_index(root: Path) -> dict[str, Any]:
    return load_json(root / "laws" / "FLCONST" / "index.json", purpose="Florida Constitution index")


def resolve(root: Path, citation: str) -> tuple[dict[str, Any], str]:
    section_id = parse_citation(citation)
    idx = load_index(root)
    entry = (idx.get("sections") or {}).get(section_id)
    if not entry:
        sample = ", ".join(list((idx.get("sections") or {}).keys())[:20])
        fail(
            f"Florida Constitution section not found: {citation!r}\n"
            f"Parsed section: {section_id!r}\n"
            f"Sample section IDs: {sample}\n"
            "Try --list-articles, --list-article <article>, or --search <keyword>."
        )
    html_path = root / "laws" / "FLCONST" / entry["path"]
    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    if not text and entry.get("textLength"):
        fail(f"Could not extract text for {citation!r}; expected anchor {entry['anchor']!r} in {html_path}")
    return entry, text


def status_banner(entry: dict[str, Any]) -> str:
    bits = []
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if entry.get("sourceUrl"):
        bits.append(entry["sourceUrl"])
    return " | ".join(bits)


def print_section(entry: dict[str, Any], text: str, *, max_bytes: int | None = None) -> None:
    print(f"=== {entry['citation']} - {entry.get('title') or ''} [{status_banner(entry)}] ===")
    if max_bytes is not None and len(text) > max_bytes:
        print(text[:max_bytes])
        print(f"\n[... truncated {len(text) - max_bytes:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
    else:
        print(text)
    if entry.get("history"):
        print()
        print(f"History.-{entry['history']}")
    if entry.get("note"):
        print(f"Note.-{entry['note']}")


def _snippet(text: str, match: re.Match[str], width: int = 90) -> str:
    start, end = match.span()
    left = max(0, start - width)
    right = min(len(text), end + width)
    chunk = re.sub(r"\s+", " ", text[left:right]).strip()
    return f"{'...' if left else ''}{chunk}{'...' if right < len(text) else ''}"


def cmd_list_articles(root: Path) -> int:
    idx = load_index(root)
    articles = idx.get("articles") or {}
    print(f"Florida Constitution - {len(articles)} articles")
    for roman in sorted(articles, key=lambda r: articles[r].get("articleNumber") or 999):
        a = articles[roman]
        print(f"  Article {roman} - {a.get('articleName','')}  [{a.get('sectionCount', 0)} sections]")
    return 0


def cmd_list_article(root: Path, article: str) -> int:
    idx = load_index(root)
    roman = normalize_article(article)
    articles = idx.get("articles") or {}
    sections = idx.get("sections") or {}
    meta = articles.get(roman)
    if not meta:
        fail(f"No Article {roman} in Florida Constitution corpus.")
    print(f"ARTICLE {roman} - {meta.get('articleName','')}")
    print(f"  {meta.get('sourceUrl','')}")
    print(f"  {meta.get('sectionCount', 0)} sections")
    for sid in meta.get("sectionIds") or []:
        e = sections.get(sid) or {}
        print(f"  § {e.get('sectionNumber')} - {e.get('title') or ''}")
    return 0


def cmd_search(
    root: Path,
    query: str,
    *,
    use_regex: bool,
    case_sensitive: bool,
    titles_only: bool,
    max_per_section: int,
    article: str | None,
) -> int:
    if not use_regex and REGEX_METACHARS.search(query):
        print(
            f"warning: pattern {query!r} contains regex metacharacters but "
            "--regex was not set; searching literally.",
            file=sys.stderr,
        )
    pattern = re.compile(query if use_regex else re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    idx = load_index(root)
    sections = idx.get("sections") or {}
    if article:
        roman = normalize_article(article)
        sections = {sid: e for sid, e in sections.items() if e.get("articleRoman") == roman}
    total = 0
    for entry in sections.values():
        title = entry.get("title") or ""
        if titles_only:
            if pattern.search(title):
                print(f"{entry['citation']} - {title}")
                print(f"  {entry.get('sourceUrl') or ''}")
                total += 1
            continue
        _, text = resolve(root, f"{entry['articleRoman']}.{entry['sectionNumber']}")
        haystack = f"{title}\n{text}"
        matches = list(pattern.finditer(haystack))
        if not matches:
            continue
        print(f"{entry['citation']} - {title}")
        print(f"  {entry.get('sourceUrl') or ''}")
        for m in matches[:max_per_section]:
            print(f"  {_snippet(haystack, m)}")
        if len(matches) > max_per_section:
            print(f"  (+{len(matches) - max_per_section} more match(es) in this section)")
        total += 1
    if total == 0:
        scope = f" Article {article}" if article else " Florida Constitution"
        print(f"No matches for {query!r} in{scope}.", file=sys.stderr)
        return 1
    return 0


def cmd_read(root: Path, citations: list[str], fmt: str, max_bytes: int | None) -> int:
    for i, citation in enumerate(citations):
        entry, text = resolve(root, citation)
        if fmt == "json":
            payload = dict(entry)
            payload["text"] = text
            payload["url"] = entry.get("sourceUrl")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        elif fmt == "markdown":
            print(f"# {entry['citation']} - {entry.get('title') or ''}")
            print()
            print(f"_{status_banner(entry)}_")
            print()
            print(text[:max_bytes] if max_bytes and len(text) > max_bytes else text)
            if entry.get("history"):
                print()
                print(f"_History.-{entry['history']}_")
            if entry.get("note"):
                print(f"_Note.-{entry['note']}_")
        else:
            if i:
                print()
            print_section(entry, text, max_bytes=max_bytes)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read/search the Florida Constitution from the bundled corpus.",
        epilog=(
            "Examples:\n"
            "  read_constitution.py 'Fla. Const. art. I, § 23'\n"
            "  read_constitution.py 'Article V section 3'\n"
            "  read_constitution.py I.1 --format markdown\n"
            "  read_constitution.py --list-articles\n"
            "  read_constitution.py --list-article X\n"
            "  read_constitution.py --search privacy\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*", help="One or more Florida Constitution citations.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--list-articles", action="store_true")
    parser.add_argument("--list-article", metavar="ARTICLE")
    parser.add_argument("--search", metavar="QUERY", help="Search section text or titles.")
    parser.add_argument("--article", help="Restrict --search to an article, e.g. I or 1.")
    parser.add_argument("--regex", action="store_true", help="Treat --search as a regular expression.")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--titles-only", action="store_true", help="With --search, match only catchline titles.")
    parser.add_argument("--max-per-section", type=int, default=2)
    parser.add_argument("--max-bytes", type=int)
    args = parser.parse_args()

    try:
        if args.list_articles:
            sys.exit(cmd_list_articles(args.root))
        if args.list_article:
            sys.exit(cmd_list_article(args.root, args.list_article))
        if args.search:
            sys.exit(cmd_search(
                args.root,
                args.search,
                use_regex=args.regex,
                case_sensitive=args.case_sensitive,
                titles_only=args.titles_only,
                max_per_section=args.max_per_section,
                article=args.article,
            ))
        if not args.citations:
            parser.error("provide citations, or use --list-articles / --list-article / --search")
        sys.exit(cmd_read(args.root, args.citations, args.format, args.max_bytes))
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
