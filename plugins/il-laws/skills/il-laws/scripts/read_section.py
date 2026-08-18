#!/usr/bin/env python3
"""Read Illinois Compiled Statutes sections and Illinois Supreme Court Rules."""

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


class AllSectionsExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cur: str | None = None
        self.in_pre = False
        self.depth = 0
        self.buf: list[str] = []
        self.results: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag == "article" and (
            (amap.get("id") or "").startswith("section-")
            or (amap.get("id") or "").startswith("rule-")
        ):
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


def default_root() -> Path:
    return ensure_corpus("il-laws")


def fail(message: str) -> None:
    raise LookupErrorWithDetail(message)


def load_json(path: Path, *, purpose: str) -> Any:
    if not path.exists():
        fail(f"Missing {purpose}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_citation(citation: str) -> tuple[str, str, str]:
    s = citation.strip()
    s = re.sub(r"§+\s*", "", s)
    s = re.sub(r"\b(?:section|sec\.)\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    m = re.search(
        r"(?P<chapter>\d+)\s+ILCS\s+(?P<act>\d+(?:\.\d+)?)\s*/\s*(?P<section>[A-Za-z0-9(). -]+)$",
        s,
        flags=re.I,
    )
    if not m:
        fail(
            f"Could not parse Illinois citation: {citation!r}\n"
            "Expected forms like '735 ILCS 5/2-619' or '815 ILCS 505/2'."
        )
    return (
        str(int(m.group("chapter"))),
        m.group("act").strip(),
        m.group("section").strip().rstrip("."),
    )


def parse_rule_citation(citation: str) -> str | None:
    s = citation.strip()
    s = re.sub(r"§+\s*", "", s)
    patterns = [
        r"^(?:IL\s+)?(?:Sup(?:reme)?\.?\s+Ct\.?|Supreme\s+Court)\s+Rule\s+([0-9][0-9A-Za-z.]*(?:-[0-9][0-9A-Za-z.]*)?)$",
        r"^Illinois\s+Supreme\s+Court\s+Rule\s+([0-9][0-9A-Za-z.]*(?:-[0-9][0-9A-Za-z.]*)?)$",
        r"^ILSCR\s+([0-9][0-9A-Za-z.]*(?:-[0-9][0-9A-Za-z.]*)?)$",
        r"^Rule\s+([0-9][0-9A-Za-z.]*(?:-[0-9][0-9A-Za-z.]*)?)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, s, flags=re.I)
        if m:
            return m.group(1).rstrip(".")
    return None


def law_map(root: Path) -> dict[str, str]:
    index = load_json(root / "index.json", purpose="Illinois master index")
    out = {}
    for law_id, law in (index.get("laws") or {}).items():
        out[f"{law['chapter']} ILCS {law['act']}"] = law_id
    return out


def resolve(root: Path, citation: str) -> tuple[dict[str, Any], str, str]:
    chapter, act, section = parse_citation(citation)
    key = f"{chapter} ILCS {act}"
    law_id = law_map(root).get(key)
    if not law_id:
        fail(f"Illinois Act not found: {key}. Try --list-acts {chapter}.")
    idx = load_json(root / "laws" / law_id / "index.json", purpose=f"Illinois law index {law_id}")
    entry = (idx.get("sections") or {}).get(section)
    if not entry:
        sample = ", ".join(list((idx.get("sections") or {}).keys())[:25])
        fail(
            f"Illinois section not found: {citation!r}\n"
            f"Parsed as {key}/{section}. Sample sections: {sample}"
        )
    html_path = root / "laws" / law_id / entry["path"]
    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    return entry, text, law_id


def resolve_rule(root: Path, citation: str) -> tuple[dict[str, Any], str, str]:
    rule_id = parse_rule_citation(citation)
    if not rule_id:
        fail(
            f"Could not parse Illinois Supreme Court Rule citation: {citation!r}\n"
            "Expected forms like 'IL Sup Ct Rule 9', 'Illinois Supreme Court Rule 9', or 'ILSCR 9'."
        )
    idx = load_json(root / "rules" / "ILSCR" / "index.json", purpose="Illinois Supreme Court Rules index")
    entry = (idx.get("rules") or {}).get(rule_id)
    if not entry:
        sample = ", ".join(list((idx.get("rules") or {}).keys())[:25])
        fail(f"Illinois Supreme Court Rule not found: {citation!r}. Sample rules: {sample}")
    html_path = root / "rules" / "ILSCR" / entry["path"]
    parser = SectionTextExtractor(entry["anchor"])
    parser.feed(html_path.read_text(encoding="utf-8"))
    text = parser.text()
    return entry, text, "ILSCR"


def banner(entry: dict[str, Any]) -> str:
    bits = [f"{entry['citation']}"]
    if entry.get("title"):
        bits.append(entry["title"])
    bits.append(f"{entry.get('textLength', 0):,} chars")
    if entry.get("sourceUrl"):
        bits.append(entry["sourceUrl"])
    return " | ".join(bits)


def list_acts(root: Path, chapter: str | None) -> None:
    index = load_json(root / "index.json", purpose="Illinois master index")
    for law_id, law in sorted((index.get("laws") or {}).items(), key=lambda kv: (int(kv[1]["chapter"]), float(kv[1]["act"]))):
        if chapter and str(law["chapter"]) != str(int(chapter)):
            continue
        print(f"{law['citationBase']:<18} {law['sectionCount']:>5}  {law['name']}")


def list_sections(root: Path, citation_base: str) -> None:
    chapter, act, _ = parse_citation(citation_base.rstrip("/") + "/0")
    law_id = law_map(root).get(f"{chapter} ILCS {act}")
    if not law_id:
        fail(f"Illinois Act not found: {chapter} ILCS {act}")
    idx = load_json(root / "laws" / law_id / "index.json", purpose=f"Illinois law index {law_id}")
    for section_id, entry in idx.get("sections", {}).items():
        title = f" — {entry['title']}" if entry.get("title") else ""
        print(f"{entry['citation']}{title}")


def list_rules(root: Path) -> None:
    idx = load_json(root / "rules" / "ILSCR" / "index.json", purpose="Illinois Supreme Court Rules index")
    def sort_key(item: tuple[str, dict[str, Any]]) -> list[int | str]:
        return [int(part) if part.isdigit() else part for part in re.split(r"([0-9]+)", item[0])]

    for rule_id, entry in sorted(idx.get("rules", {}).items(), key=sort_key):
        title = f" — {entry['title']}" if entry.get("title") else ""
        article = f" [{entry['article']}]" if entry.get("article") else ""
        page = f" p.{entry['pdfPage']}" if entry.get("pdfPage") else ""
        print(f"{entry['citation']}{title}{article}{page}")


def search(root: Path, phrase: str, *, titles_only: bool = False, limit: int = 100) -> None:
    if limit < 1:
        fail("--limit must be a positive integer.")
    needle = phrase.lower()
    master = load_json(root / "index.json", purpose="Illinois master index")
    hits = 0
    for law_id in master.get("laws", {}):
        idx = load_json(root / "laws" / law_id / "index.json", purpose=f"Illinois law index {law_id}")
        html_path = root / "laws" / law_id / "sections.html"
        texts: dict[str, str] = {}
        if not titles_only:
            parser = AllSectionsExtractor()
            parser.feed(html_path.read_text(encoding="utf-8"))
            texts = parser.results
        for entry in idx.get("sections", {}).values():
            hay = entry.get("title") or ""
            if not titles_only:
                hay += "\n" + texts.get(entry["anchor"], "")
            if needle in hay.lower():
                print(f"{entry['citation']} — {entry.get('title') or ''}")
                hits += 1
                if hits >= limit:
                    return
    rules_index_path = root / "rules" / "ILSCR" / "index.json"
    if rules_index_path.exists():
        idx = load_json(rules_index_path, purpose="Illinois Supreme Court Rules index")
        html_path = root / "rules" / "ILSCR" / "sections.html"
        texts: dict[str, str] = {}
        if not titles_only:
            parser = AllSectionsExtractor()
            parser.feed(html_path.read_text(encoding="utf-8"))
            texts = parser.results
        for entry in idx.get("rules", {}).values():
            hay = entry.get("title") or ""
            if not titles_only:
                hay += "\n" + texts.get(entry["anchor"], "")
            if needle in hay.lower():
                print(f"{entry['citation']} — {entry.get('title') or ''}")
                hits += 1
                if hits >= limit:
                    return


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read Illinois Compiled Statutes sections and Illinois Supreme Court Rules.",
        epilog=(
            "Examples:\n"
            "  read_section.py '735 ILCS 5/2-619'\n"
            "  read_section.py 'IL Sup Ct Rule 9'\n"
            "  read_section.py --list-acts 735\n"
            "  read_section.py --list '735 ILCS 5/'\n"
            "  read_section.py --search 'consumer fraud' --limit 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--max-bytes", type=int, default=0)
    parser.add_argument("--list-acts", nargs="?", const="", metavar="CHAPTER")
    parser.add_argument("--list", metavar="ACT_CITATION")
    parser.add_argument("--list-rules", action="store_true")
    parser.add_argument("--search", metavar="PHRASE")
    parser.add_argument("--titles-only", action="store_true")
    parser.add_argument(
        "--limit",
        "--max-results",
        type=int,
        default=100,
        help="With --search, maximum matching citations/titles to print (default 100).",
    )
    args = parser.parse_args()

    try:
        if args.list_acts is not None:
            list_acts(args.root, args.list_acts or None)
            return 0
        if args.list:
            list_sections(args.root, args.list)
            return 0
        if args.list_rules:
            list_rules(args.root)
            return 0
        if args.search:
            search(args.root, args.search, titles_only=args.titles_only, limit=args.limit)
            return 0
        if not args.citations:
            parser.error("provide a citation, --list-acts, --list, or --search")
        results = []
        for citation in args.citations:
            if parse_rule_citation(citation):
                entry, text, _ = resolve_rule(args.root, citation)
            else:
                entry, text, _ = resolve(args.root, citation)
            if args.max_bytes and len(text.encode("utf-8")) > args.max_bytes:
                text = text.encode("utf-8")[: args.max_bytes].decode("utf-8", errors="ignore")
                text += "\n[... truncated ...]"
            results.append({"entry": entry, "text": text})
        if args.format == "json":
            print(json.dumps(results, indent=2, sort_keys=True))
        elif args.format == "markdown":
            for result in results:
                entry = result["entry"]
                print(f"## {entry['citation']}")
                if entry.get("title"):
                    print(f"**{entry['title']}**\n")
                print("```text")
                print(result["text"])
                print("```\n")
        else:
            for result in results:
                print(banner(result["entry"]))
                print(result["text"])
                if result is not results[-1]:
                    print()
        return 0
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
