#!/usr/bin/env python3
"""Read and search the Ohio Revised Code and Constitution corpus."""

import argparse
import json
import re
from html.parser import HTMLParser

from corpus import ensure_corpus


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing corpus file: {path}")


ROOT = ensure_corpus("oh-laws")


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.pre = False
        self.buf = []
        self.results = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.current = attrs.get("id")
            self.buf = []
        elif self.current and tag == "pre":
            self.pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.pre = False
        elif tag == "article" and self.current:
            self.results[self.current] = "".join(self.buf)
            self.current = None

    def handle_data(self, data):
        if self.current and self.pre:
            self.buf.append(data)


def parse(value):
    constitution = bool(re.search(r"(?i)const", value))
    value = re.sub(r"(?i)^.*?(?:code|§)\s*", "", value).strip() if not constitution else value
    if constitution:
        match = re.search(r"(?i)(?:art(?:icle)?\.?\s*)?([IVXLCDM]+|\d+)\s*[,.:]?\s*(?:§|sec(?:tion)?\.?)?\s*(\d+[A-Za-z-]*)", value)
        if not match:
            raise SystemExit("Expected e.g. 'Ohio Const. art. I, § 1'.")
        return "constitution", f"{match.group(1).upper()}.{match.group(2)}"
    match = re.search(r"(\d+\.\d+[A-Za-z]?)", value)
    if not match:
        raise SystemExit("Expected e.g. 'ORC 2903.01'.")
    section = match.group(1)
    chapter = section.split(".")[0]
    return chapter[:-2] if len(chapter) > 2 else str(int(chapter) // 100), section


def resolve(value):
    scope, section = parse(value)
    folder = ROOT / scope if scope == "constitution" else ROOT / "titles" / scope
    entry = load_json(folder / "index.json")["sections"].get(section)
    if not entry:
        raise SystemExit(f"{section} not found.")
    extractor = Extractor()
    extractor.feed((folder / entry["path"]).read_text(encoding="utf-8"))
    return entry, extractor.results.get(entry["anchor"], "")


def search(query, limit):
    pattern = re.compile(re.escape(query), re.I)
    master = load_json(ROOT / "index.json")
    folders = [ROOT / "constitution"] + [ROOT / "titles" / name for name in master["titles"]]
    found = 0
    for folder in folders:
        index = load_json(folder / "index.json")
        extractor = Extractor()
        extractor.feed((folder / "sections.html").read_text(encoding="utf-8"))
        for entry in index["sections"].values():
            text = extractor.results.get(entry["anchor"], "")
            if pattern.search(text):
                print(f"{entry['citation']} — {entry['title']}")
                found += 1
            if found >= limit:
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("citations", nargs="*")
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    args = parser.parse_args()
    if args.search:
        return search(args.search, args.limit)
    if not args.citations:
        parser.error("provide a citation or --search")
    for citation in args.citations:
        entry, text = resolve(citation)
        shown = text[: args.max_bytes] if args.max_bytes else text
        if args.format == "json":
            print(json.dumps({**entry, "text": text}, indent=2))
        elif args.format == "markdown":
            print(f"# {entry['citation']} — {entry['title']}\n\n_{entry['sourceUrl']}_\n\n{shown}")
        else:
            print(f"{entry['citation']} — {entry['title']} | {entry['sourceUrl']}\n{shown}")


if __name__ == "__main__":
    main()
