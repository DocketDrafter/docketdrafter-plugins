#!/usr/bin/env python3
"""Look up and search the Massachusetts General Laws."""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

from corpus import ensure_corpus


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.in_pre = False
        self.buf = []
        self.results = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.current = attrs.get("id")
            self.buf = []
        elif self.current and tag == "pre":
            self.in_pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False
        elif tag == "article" and self.current:
            self.results[self.current] = "".join(self.buf)
            self.current = None

    def handle_data(self, data):
        if self.current and self.in_pre:
            self.buf.append(data)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing corpus file: {path}")


def parse_citation(value: str) -> tuple[str, str]:
    value = value.strip().replace("½", "1/2")
    patterns = [
        r"(?i)(?:mass(?:achusetts)?\.?(?:\s+gen(?:eral)?\.?)?\s+laws?|m\.?g\.?l\.?|g\.?l\.?)?\s*(?:c(?:h(?:apter)?)?\.?)\s*([0-9]+[A-Z]*(?:1/2)?)\s*[,;:]?\s*(?:§+|s(?:ec(?:tion)?)?\.?)\s*([0-9][0-9A-Z. /,-]*)$",
        r"(?i)^chapter\s+([0-9]+[A-Z]*(?:1/2)?)\s*[,;:]\s*(?:section|sec\.?|§+)\s*([0-9][0-9A-Z. /,-]*)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            chapter = re.sub(r"\s+", "", match.group(1)).upper()
            section = re.sub(r"\s+", " ", match.group(2)).strip().rstrip(".,")
            return chapter, section
    raise SystemExit(
        f"Could not parse Massachusetts citation {value!r}; expected e.g. "
        "'Mass. Gen. Laws ch. 93A, § 2' or 'M.G.L. c. 260, § 2A'."
    )


def corpus_root(argument: Path | None) -> Path:
    return argument if argument else ensure_corpus("ma-laws")


def resolve(root: Path, citation: str):
    chapter, section = parse_citation(citation)
    master = load(root / "index.json")
    chapter_entry = master["chapters"].get(chapter.casefold())
    if not chapter_entry:
        raise SystemExit(f"Massachusetts General Laws chapter {chapter} not found.")
    index_path = root / chapter_entry["path"]
    index = load(index_path)
    entry = index["sections"].get(section.casefold())
    if not entry:
        nearby = [item["sectionId"] for item in index["sections"].values()
                  if item["sectionId"].casefold().startswith(section[:1].casefold())][:20]
        raise SystemExit(f"Section {section} not found in chapter {chapter}. Nearby: {', '.join(nearby) or 'none'}")
    parser = Extractor()
    parser.feed((index_path.parent / entry["path"]).read_text(encoding="utf-8"))
    return entry, parser.results.get(entry["anchor"], "")


def list_chapters(root: Path):
    master = load(root / "index.json")
    for entry in master["chapters"].values():
        print(f"Chapter {entry['chapter']:<8} {entry['sectionCount']:>4} sections | {entry['sourceUrl']}")


def list_sections(root: Path, chapter: str):
    master = load(root / "index.json")
    item = master["chapters"].get(chapter.replace("½", "1/2").casefold())
    if not item:
        raise SystemExit(f"Massachusetts General Laws chapter {chapter} not found.")
    index = load(root / item["path"])
    for entry in index["sections"].values():
        print(f"{entry['citation']} — {entry['title']} | {entry['sourceUrl']}")


def search(root: Path, query: str, limit: int, titles_only: bool):
    if limit < 1:
        raise SystemExit("--limit must be positive")
    needle = query.casefold()
    master = load(root / "index.json")
    found = 0
    for chapter in master["chapters"].values():
        index_path = root / chapter["path"]
        index = load(index_path)
        texts = {}
        if not titles_only:
            parser = Extractor()
            parser.feed((index_path.parent / "sections.html").read_text(encoding="utf-8"))
            texts = parser.results
        for entry in index["sections"].values():
            text = texts.get(entry["anchor"], "")
            haystack = entry["title"] if titles_only else entry["title"] + "\n" + text
            position = haystack.casefold().find(needle)
            if position < 0:
                continue
            print(f"{entry['citation']} — {entry['title']} | {entry['sourceUrl']}")
            if not titles_only:
                snippet = re.sub(r"\s+", " ", haystack[max(0, position - 70):position + len(query) + 100])
                print(f"  …{snippet}…")
            found += 1
            if found >= limit:
                return 0
    if not found:
        print(f"No matches for {query!r}.", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("citations", nargs="*")
    parser.add_argument("--root", type=Path, help="use a local references directory")
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--search")
    parser.add_argument("--titles-only", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--list-chapters", action="store_true")
    parser.add_argument("--list-chapter")
    args = parser.parse_args()
    root = corpus_root(args.root)
    if args.list_chapters:
        return list_chapters(root)
    if args.list_chapter:
        return list_sections(root, args.list_chapter)
    if args.search:
        return search(root, args.search, args.limit, args.titles_only)
    if not args.citations:
        parser.error("provide a citation or a list/search option")
    results = []
    for citation in args.citations:
        entry, text = resolve(root, citation)
        shown = text
        if args.max_bytes and len(shown.encode("utf-8")) > args.max_bytes:
            shown = shown.encode("utf-8")[:args.max_bytes].decode("utf-8", errors="ignore") + "\n[... truncated ...]"
        results.append((entry, text, shown))
    if args.format == "json":
        print(json.dumps([{**entry, "text": text} for entry, text, _ in results], indent=2, ensure_ascii=False))
    else:
        for number, (entry, _, shown) in enumerate(results):
            if number:
                print()
            if args.format == "markdown":
                print(f"# {entry['citation']} — {entry['title']}\n\n<{entry['sourceUrl']}>\n\n{shown}")
            else:
                print(f"{entry['citation']} — {entry['title']} | {entry['textLength']:,} chars | {entry['sourceUrl']}")
                print(shown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
