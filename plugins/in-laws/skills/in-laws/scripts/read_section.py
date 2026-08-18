#!/usr/bin/env python3
"""Read and search the bundled Indiana Code of Laws."""
from __future__ import annotations
import argparse, html, json, re, sys
from html.parser import HTMLParser
from pathlib import Path
from corpus import ensure_corpus

ROOT = ensure_corpus("in-laws")

class Extractor(HTMLParser):
    def __init__(self, target=None):
        super().__init__(convert_charrefs=True); self.target=target; self.current=None; self.in_pre=False; self.buf=[]; self.results={}
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="article": self.current=a.get("id"); self.buf=[]
        elif self.current and tag=="pre": self.in_pre=True
    def handle_endtag(self, tag):
        if tag=="pre": self.in_pre=False
        elif tag=="article" and self.current:
            self.results[self.current]="".join(self.buf); self.current=None
    def handle_data(self, data):
        if self.current and self.in_pre: self.buf.append(data)

def load(path):
    try: return json.loads(path.read_text())
    except FileNotFoundError: raise SystemExit(f"Missing corpus file: {path}")

def parse_citation(value):
    value=re.sub(r"(?i)^\s*(?:Indiana\s+Code|Ind\.?\s+Code|IC)\s*", "", value)
    value=value.replace("§", "").strip().rstrip(".")
    if not re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)+", value):
        raise SystemExit(f"Could not parse Indiana citation {value!r}; expected e.g. '35-42-1-1'.")
    return value

def title_index(number): return load(ROOT/f"Title{number}"/"index.json")

def resolve(citation):
    sid=parse_citation(citation); number=sid.split("-",1)[0]; idx=title_index(number); entry=idx["sections"].get(sid)
    if not entry:
        near=[x for x in idx["sections"] if x.startswith("-".join(sid.split("-")[:2]))][:20]
        raise SystemExit(f"Section {sid} not found. Nearby sections: {', '.join(near) or 'none'}")
    p=Extractor(); p.feed((ROOT/f"Title{number}"/entry["path"]).read_text()); return entry,p.results.get(entry["anchor"],"")

def banner(e): return f"{e['citation']} — {e['title']} | {e['textLength']:,} chars | {e['sourceUrl']}"

def list_titles():
    data=load(ROOT/"index.json")
    for n,t in data["titles"].items(): print(f"Title {n}: {t['name']} ({t['sectionCount']} sections)")

def list_sections(number, chapter=None):
    number=str(number).removeprefix("Title").strip()
    idx=title_index(number); print(f"Title {number}: {idx.get('title','')}")
    for sid,e in idx["sections"].items():
        parts=sid.split("-")
        section_chapter=parts[1] if len(parts)>2 else None
        if chapter and section_chapter != str(chapter): continue
        context=f" [Ch. {section_chapter}]" if section_chapter else ""
        print(f"  § {sid} — {e['title']}{context}")

def search(query, scopes, regex=False, titles_only=False, max_hits=100):
    pattern=re.compile(query if regex else re.escape(query), re.I); master=load(ROOT/"index.json")
    nums=[x.replace("Title","").strip() for x in scopes] if scopes else list(master["titles"])
    found=0
    for n in nums:
        idx=title_index(n); xp=None
        if not titles_only:
            xp=Extractor(); xp.feed((ROOT/f"Title{n}"/"sections.html").read_text())
        for sid,e in idx["sections"].items():
            text=e["title"] if titles_only else xp.results.get(e["anchor"],"")
            m=pattern.search(text)
            if not m: continue
            print(f"{e['citation']} — {e['title']}")
            if not titles_only:
                snippet=re.sub(r"\s+"," ",text[max(0,m.start()-80):m.end()+80]); print(f"  …{snippet}…")
            found+=1
            if found>=max_hits: return 0
    if not found: print(f"No matches for {query!r}.",file=sys.stderr); return 1
    return 0

def main():
    ap=argparse.ArgumentParser(description="Read/search the Indiana Code of Laws")
    ap.add_argument("citations",nargs="*"); ap.add_argument("--format",choices=["text","markdown","json"],default="text")
    ap.add_argument("--max-bytes",type=int); ap.add_argument("--list-titles",action="store_true")
    ap.add_argument("--list-title",metavar="N"); ap.add_argument("--chapter")
    ap.add_argument("--search"); ap.add_argument("--regex",action="store_true"); ap.add_argument("--titles-only",action="store_true"); ap.add_argument("--max-hits",type=int,default=100)
    a=ap.parse_args()
    if a.list_titles: return list_titles()
    if a.list_title: return list_sections(a.list_title,a.chapter)
    if a.search: return search(a.search,a.citations,a.regex,a.titles_only,a.max_hits)
    if not a.citations: ap.error("provide a citation or a list/search option")
    for i,c in enumerate(a.citations):
        e,text=resolve(c); shown=text
        if a.max_bytes and len(shown)>a.max_bytes:
            omitted = len(shown) - a.max_bytes
            shown = shown[:a.max_bytes] + f"\n\n[truncated {omitted:,} of {len(text):,} chars]"
        if a.format=="json": print(json.dumps({**e,"text":text},indent=2,ensure_ascii=False))
        elif a.format=="markdown": print(f"# {e['citation']} — {e['title']}\n\n_{e['sourceUrl']}_\n\n{shown}")
        else: print(("\n" if i else "")+banner(e)+"\n"+shown)
    return 0
if __name__=="__main__": raise SystemExit(main())
