#!/usr/bin/env python3
"""Read and search the bundled Florida court rules corpus."""

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


class RuleHtmlExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_rule_text = False
        self.in_note = False
        self.in_note_pre = False
        self.note_type: str | None = None
        self.rule_text_parts: list[str] = []
        self.note_parts: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        amap = dict(attrs)
        if tag == "pre" and amap.get("class") == "rule-text":
            self.in_rule_text = True
        elif tag == "section" and amap.get("class") == "rule-note":
            self.in_note = True
            self.note_type = amap.get("data-note-type") or "Note"
            self.note_parts.setdefault(self.note_type, [])
        elif self.in_note and tag == "pre":
            self.in_note_pre = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self.in_rule_text:
            self.in_rule_text = False
        elif tag == "pre" and self.in_note_pre:
            self.in_note_pre = False
        elif tag == "section" and self.in_note:
            self.in_note = False
            self.note_type = None

    def handle_data(self, data: str) -> None:
        if self.in_rule_text:
            self.rule_text_parts.append(data)
        elif self.in_note_pre and self.note_type:
            self.note_parts.setdefault(self.note_type, []).append(data)

    def text(self, *, include_notes: bool = True) -> str:
        parts = ["".join(self.rule_text_parts).strip()]
        if include_notes:
            for label, note_parts in self.note_parts.items():
                note = "".join(note_parts).strip()
                if note:
                    parts.append(f"{label}\n\n{note}")
        return "\n\n".join(p for p in parts if p)

    def notes(self) -> dict[str, str]:
        return {label: "".join(parts).strip() for label, parts in self.note_parts.items()}


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


def normalize_rule(rule: str) -> str:
    return rule.strip().removeprefix("rule").strip().rstrip(".")


def parse_citation(citation: str) -> tuple[str, str]:
    s = citation.strip()
    s = re.sub(r"\b(?:rule|form)\b", "", s, flags=re.IGNORECASE)
    replacements = [
        (r"fla\.?\s*r\.?\s*gen\.?\s*prac\.?\s*&?\s*jud\.?\s*admin\.?", " FLRGPJA "),
        (r"fla\.?\s*r\.?\s*civ\.?\s*p\.?\s*svp", " FLSVP "),
        (r"fla\.?\s*r\.?\s*civ\.?\s*p\.?", " FLRCP "),
        (r"fla\.?\s*r\.?\s*crim\.?\s*p\.?", " FLRCrimP "),
        (r"fla\.?\s*prob\.?\s*r\.?", " FLProbR "),
        (r"fla\.?\s*r\.?\s*traf\.?\s*ct\.?", " FLRTrafP "),
        (r"fla\.?\s*sm\.?\s*cl\.?\s*r\.?", " FLSmClR "),
        (r"fla\.?\s*r\.?\s*juv\.?\s*p\.?", " FLRJuvP "),
        (r"fla\.?\s*r\.?\s*app\.?\s*p\.?", " FLRAppP "),
        (r"fla\.?\s*fam\.?\s*l\.?\s*r\.?\s*p\.?", " FLFamLRP "),
    ]
    for pattern, replacement in replacements:
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    s = " ".join(s.split())
    if re.fullmatch(r"\d+\.\d+", s):
        return infer_prefix_from_rule_num(s), s
    m = re.match(r"(?P<prefix>.+?)\s+(?P<rule>\d+\.\d+)\.?$", s)
    if not m:
        fail(
            f"Could not parse Florida rule citation: {citation!r}\n"
            "Expected forms: '1.500', 'FLRCP 1.500', 'Fla. R. Civ. P. 1.500'."
        )
    return m.group("prefix").strip(), normalize_rule(m.group("rule"))


def infer_prefix_from_rule_num(rule_num: str) -> str:
    chapter = int(rule_num.split(".", 1)[0])
    return {
        1: "FLRCP",
        2: "FLRGPJA",
        3: "FLRCrimP",
        4: "FLSVP",
        5: "FLProbR",
        6: "FLRTrafP",
        7: "FLSmClR",
        8: "FLRJuvP",
        9: "FLRAppP",
        12: "FLFamLRP",
    }.get(chapter, "FLRCP")


def resolve_ruleset_id(root: Path, prefix: str) -> str:
    aliases = load_json(root / "rule_aliases.json", purpose="Florida rule aliases index")
    ruleset_id = aliases.get(prefix) or aliases.get(prefix.upper()) or aliases.get(prefix.lower())
    if not ruleset_id:
        fail(
            f"Unknown Florida rule alias: {prefix!r}. Known aliases: "
            + ", ".join(sorted(aliases))
        )
    return ruleset_id


def _load_ruleset_index(root: Path) -> dict[str, Any]:
    return load_json(root / "rules" / "FLRCP" / "index.json",
                     purpose="Florida Rules of Civil Procedure index")


def load_master_index(root: Path) -> dict[str, Any]:
    return load_json(root / "index.json", purpose="Florida master index")


def iter_ruleset_ids(root: Path) -> list[str]:
    master = load_master_index(root)
    rulesets = master.get("rulesets") or {}
    return sorted(rulesets, key=lambda rid: int((rulesets[rid] or {}).get("chapter") or 999))


def load_ruleset_index(root: Path, ruleset_id: str) -> dict[str, Any]:
    return load_json(root / "rules" / ruleset_id / "index.json",
                     purpose=f"Florida rules index for {ruleset_id}")


def resolve(root: Path, citation: str, *, include_notes: bool) -> tuple[dict[str, Any], str, dict[str, str]]:
    prefix, rule_num = parse_citation(citation)
    ruleset_id = resolve_ruleset_id(root, prefix)
    idx = load_json(root / "rules" / ruleset_id / "index.json",
                    purpose=f"Florida rules index for {ruleset_id}")
    entry = (idx.get("rules") or {}).get(rule_num)
    if not entry:
        sample = ", ".join(list((idx.get("rules") or {}).keys())[:20])
        fail(
            f"Florida rule not found: {citation!r}\n"
            f"Parsed rule: {rule_num!r}\n"
            f"Sample rule IDs: {sample}\n"
            "Try --list-rules or --search <keyword>."
        )
    html_path = root / "rules" / ruleset_id / entry["path"]
    parser = RuleHtmlExtractor()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return entry, parser.text(include_notes=include_notes), parser.notes()


def status_banner(entry: dict[str, Any]) -> str:
    bits = []
    if entry.get("textLength"):
        bits.append(f"{entry['textLength']:,} chars")
    if entry.get("sourceUrl"):
        bits.append(entry["sourceUrl"])
    if entry.get("sourcePdf"):
        bits.append(entry["sourcePdf"])
    return " | ".join(bits)


def _snippet(text: str, match: re.Match[str], width: int = 90) -> str:
    start, end = match.span()
    left = max(0, start - width)
    right = min(len(text), end + width)
    chunk = re.sub(r"\s+", " ", text[left:right]).strip()
    return f"{'...' if left else ''}{chunk}{'...' if right < len(text) else ''}"


def cmd_list_rules(root: Path) -> int:
    master = load_master_index(root)
    for ruleset_id in iter_ruleset_ids(root):
        idx = load_ruleset_index(root, ruleset_id)
        rules = idx.get("rules") or {}
        meta = (master.get("rulesets") or {}).get(ruleset_id) or {}
        print(f"{ruleset_id} — {meta.get('name') or ruleset_id} — {len(rules)} entries")
        for rule_num in sorted(rules, key=lambda x: [int(p) for p in x.split(".")]):
            entry = rules[rule_num]
            print(f"  {entry.get('kind', 'RULE').title()} {rule_num} — {entry.get('title') or ''}")
    return 0


def cmd_search(
    root: Path,
    query: str,
    *,
    use_regex: bool,
    case_sensitive: bool,
    titles_only: bool,
    max_per_rule: int,
    include_notes: bool,
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
    indexes = [(ruleset_id, load_ruleset_index(root, ruleset_id)) for ruleset_id in iter_ruleset_ids(root)]
    total = 0
    for ruleset_id, idx in indexes:
        for entry in (idx.get("rules") or {}).values():
            title = entry.get("title") or ""
            if titles_only:
                if pattern.search(title):
                    print(f"{entry['citation']} — {title}")
                    print(f"  {entry.get('sourceUrl') or ''}")
                    total += 1
                continue
            _, text, _ = resolve(root, f"{ruleset_id} {entry['ruleNum']}", include_notes=include_notes)
            haystack = f"{title}\n{text}"
            matches = list(pattern.finditer(haystack))
            if not matches:
                continue
            print(f"{entry['citation']} — {title}")
            print(f"  {entry.get('sourceUrl') or ''}")
            for m in matches[:max_per_rule]:
                print(f"  {_snippet(haystack, m)}")
            if len(matches) > max_per_rule:
                print(f"  (+{len(matches) - max_per_rule} more match(es) in this rule)")
            total += 1
    if total == 0:
        print(f"No matches for {query!r} in Florida court rules.", file=sys.stderr)
        return 1
    return 0


def cmd_read(root: Path, citations: list[str], fmt: str, max_bytes: int | None, include_notes: bool) -> int:
    for i, citation in enumerate(citations):
        entry, text, notes = resolve(root, citation, include_notes=include_notes)
        if fmt == "json":
            payload = dict(entry)
            payload["text"] = text
            payload["notes"] = notes
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        elif fmt == "markdown":
            print(f"# {entry['citation']} — {entry.get('title') or ''}")
            print()
            print(f"_{status_banner(entry)}_")
            print()
            print(text[:max_bytes] if max_bytes and len(text) > max_bytes else text)
        else:
            if i:
                print()
            print(f"=== {entry['citation']} - {entry.get('title') or ''} [{status_banner(entry)}] ===")
            if max_bytes is not None and len(text) > max_bytes:
                print(text[:max_bytes])
                print(f"\n[... truncated {len(text) - max_bytes:,} of {len(text):,} chars by --max-bytes {max_bytes} ...]")
            else:
                print(text)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read/search Florida court rules from the bundled corpus.",
        epilog=(
            "Examples:\n"
            "  read_rule.py '1.500'\n"
            "  read_rule.py 'Fla. R. Civ. P. 1.500' --omit-notes\n"
            "  read_rule.py 'Fla. Sm. Cl. R. 7.090'\n"
            "  read_rule.py '2.514'\n"
            "  read_rule.py --list-rules\n"
            "  read_rule.py --search default\n"
            "  read_rule.py --search default --omit-notes\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("citations", nargs="*", help="One or more Florida rule citations.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument("--list-rules", action="store_true")
    parser.add_argument("--search", metavar="QUERY", help="Search rule text or titles.")
    parser.add_argument("--regex", action="store_true",
                        help="Treat --search as a regular expression.")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--titles-only", action="store_true",
                        help="With --search, match only rule titles.")
    parser.add_argument("--max-per-rule", type=int, default=2)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--omit-notes", action="store_true",
                        help="Omit committee notes and court commentary from reads/searches.")
    args = parser.parse_args()

    include_notes = not args.omit_notes
    try:
        if args.list_rules:
            sys.exit(cmd_list_rules(args.root))
        if args.search:
            sys.exit(cmd_search(
                args.root,
                args.search,
                use_regex=args.regex,
                case_sensitive=args.case_sensitive,
                titles_only=args.titles_only,
                max_per_rule=args.max_per_rule,
                include_notes=include_notes,
            ))
        if not args.citations:
            parser.error("provide citations, or use --list-rules / --search")
        sys.exit(cmd_read(args.root, args.citations, args.format, args.max_bytes, include_notes))
    except LookupErrorWithDetail as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
