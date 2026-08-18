---
name: il-laws
description: Use when an agent needs to look up, quote, summarize, cite, or reason from Illinois Compiled Statutes or Illinois Supreme Court Rules. Provides local access to ILCS sections and court rules through compact HTML files and a citation lookup script.
---

# Illinois Laws

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill when a task requires Illinois statutory text, Illinois Supreme Court Rules, section lookup, citation checking, or analysis based on Illinois Compiled Statutes sections or Illinois court rules.

## Corpus layout

All data lives under `references/`:

- `references/index.json` — master index. Top-level `laws` is a `{lawId: {name, citationBase, chapter, act, sectionCount, ...}}` map covering each ILCS Act.
- `references/aliases.json` — general aliases for the corpus (`ILCS`, `Ill. Comp. Stat.`, `Illinois Compiled Statutes`).
- `references/laws/{lawId}/law.json` — per-Act metadata: `name`, `chapter`, `act`, `citationBase`, `chapterName`, `title`, `cite`, `source`, `shortTitle`, `sourceUrl`, `publicActUrl`.
- `references/laws/{lawId}/index.json` — `{lawId, format, articles, sections}`. Each section entry has `sectionId`, `citation`, `title`, `path`, `anchor`, `article`, `sourceUrl`, `publicActUrl`, `rawPath`, `docId`, and `textLength`.
- `references/laws/{lawId}/sections.html` — all section text for that Act in one HTML file, each section wrapped in `<article id="section-...">`.
- `references/rules/ILSCR/index.json` — Illinois Supreme Court Rules parsed from the official compiled PDF. Each rule entry has `ruleId`, `citation`, `title`, `path`, `anchor`, `article`, `pdfPage`, `sourceUrl`, and `textLength`.
- `references/rules/ILSCR/sections.html` — all Supreme Court Rule text, each rule wrapped in `<article id="rule-...">`. Rule `sourceUrl` values include `#page=N` PDF fragments for page-specific links.

The corpus is built from the Illinois General Assembly FTP HTML snapshot. It was updated on `2025-11-21` with Public Acts through `104-433`. The source states that the printed copy maintained by the Secretary of State is official; this corpus is not an official legal source.

The build preserves ILGA FTP URLs as exact `sourceUrl` values. `publicActUrl` is a derived Justia Act URL for convenient public browsing; it is Act-level, not section-level.

The Illinois Supreme Court Rules source is the official compiled PDF titled `Illinois Supreme Court Rules`, current May 29, 2026. The local text layer was extracted with `pdftotext -layout` and indexed by rule heading.

## Lookup script

`scripts/read_section.py` handles citation resolution, discovery, and listing. Run `python scripts/read_section.py --help` for the current complete option list.

### Read one or more sections

```bash
python scripts/read_section.py "735 ILCS 5/2-619"
python scripts/read_section.py "815 ILCS 505/2"
python scripts/read_section.py "IL Sup Ct Rule 9"
python scripts/read_section.py "Illinois Supreme Court Rule 21"
python scripts/read_section.py "ILSCR 30"
python scripts/read_section.py "25 ILCS 5/1" --format json
python scripts/read_section.py "735 ILCS 5/2-619" --format markdown
```

Plain text is the default. Every read prints a one-line banner showing citation, title when available, character count, and the ILGA FTP source URL.

### Cap output size

```bash
python scripts/read_section.py "735 ILCS 5/2-619" --max-bytes 4000
```

Truncates each section's text at the byte limit with a clear marker. Useful for long sections.

### Discover what's in the corpus

```bash
python scripts/read_section.py --list-acts
python scripts/read_section.py --list-acts 815
python scripts/read_section.py --list "735 ILCS 5/"
python scripts/read_section.py --list-rules
```

`--list-acts <chapter>` lists ILCS Acts in one chapter. `--list "<chapter> ILCS <act>/"` lists sections in one Act.

### Search

```bash
python scripts/read_section.py --search "consumer fraud"
python scripts/read_section.py --search "involuntary dismissal" --titles-only
python scripts/read_section.py --search "Electronic Filing Required" --limit 20
```

Search reports matching citations and titles across ILCS sections and Illinois Supreme Court Rules. Use `--limit` or `--max-results` to control the number of hits. Search does not print snippets; after finding a promising hit, read that citation directly and use `--max-bytes` if the section is long. Whole-corpus full-text search can be slower than direct citation lookup because it scans the bundled Act HTML files and rule HTML.

## Citation workflow

1. If the user gives a citation, resolve it with `scripts/read_section.py "<chapter> ILCS <act>/<section>"`.
2. If the user gives an Illinois Supreme Court Rule citation, resolve it with `scripts/read_section.py "IL Sup Ct Rule <rule>"`.
3. If the Act is unknown, run `--list-acts <chapter>`.
4. If the section ID is unknown, run `--list "<chapter> ILCS <act>/"`.
5. For topic-based discovery, use `--search "<phrase>" --limit N`, then read selected hits directly.
6. Quote only the exact statutory or rule language needed.
7. Cite statutes in ILCS form, e.g. `735 ILCS 5/2-619`; cite rules as `IL Sup Ct Rule 9`.
8. State that this corpus is an ILGA FTP snapshot and is not the official printed Illinois Compiled Statutes if source authority matters.

## Known limitations

- The corpus contains ILCS statutory text from the FTP HTML files. It does not include case annotations, editorial annotations, or commercial research notes.
- Currency is the FTP snapshot date: `2025-11-21`, Public Acts through `104-433`.
- The derived Justia `publicActUrl` is Act-level only. Section-level public URLs are not currently included.
