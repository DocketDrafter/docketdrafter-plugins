---
name: ny-laws
description: Use when an agent needs to look up, quote, summarize, cite, or reason from New York State statutes, the New York State Constitution, the New York City Administrative Code, or New York Unified Court System rules. Provides local full-corpus access through compact HTML files and a citation lookup script.
---

# New York Laws

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill when a task requires New York statutory text, the New York State Constitution, New York City Administrative Code text, New York Unified Court System rules, section lookup, citation checking, or legal analysis based on New York law or court-rule sections.

## Corpus layout

All data lives under `references/`:

- `references/index.json` — master index. Top-level `laws` is a `{lawId: {name, commonAliases, sectionCount, activeDate, ...}}` map covering every NY law in the corpus.
- `references/aliases.json` — flat `{prefix → lawId}` map (e.g. `"CPLR" → "CVP"`, `"VTL" → "VAT"`, `"ABC" → "ABC"`). 400+ entries including UPPERCASE variants and full law names.
- `references/laws/{lawId}/law.json` — per-law metadata: `name`, `lawType`, `chapter`, `activeDate`, `publishedDates`, `sourceUrl`.
- `references/laws/{lawId}/index.json` — `{lawId, format, sections: {sectionId: entry}}`. Each `entry` has: `title`, `citation`, `path`, `anchor`, `activeDate`, `repealed`, `repealedDate`, `docLevelId`, `article`, `articleTitle`, `textLength`.
- `references/laws/{lawId}/sections.html` — all section text for that law in one HTML file, each section wrapped in `<article id="section-...">`.

The New York State Constitution is bundled as law `CNS`. Common aliases include `CNS`, `Constitution`, `NY Constitution`, `New York Constitution`, and `New York State Constitution`.

The New York City Administrative Code is bundled as synthetic law `NYCAC`:

- `references/laws/NYCAC/index.json` — NYC Admin Code section index. Entries include normal lookup fields plus `titleNumber`, `titleTitle`, `chapter`, `chapterTitle`, `sourceRecordId`, `sourceAnchor`, and clickable AmLegal `sourceUrl`.
- `references/laws/NYCAC/titles/*.html` — section text split by title (`T01.html`, `T28.html`, etc.) plus `appendices.html` for local-law appendix material.

Selected Title 22 NYCRR appellate rules are bundled as synthetic law `NYCRR22`:

- `references/laws/NYCRR22/index.json` — 22 NYCRR Part 500 Court of Appeals rules, Part 1250 statewide Appellate Division practice rules, and Part 600 First Department supplemental rules.
- `references/laws/NYCRR22/sections.html` — compact section text.
- Common aliases include `NYCRR22`, `Part 500`, `22 NYCRR Part 500`, `Part 1250`, and `Part 600`. Broad `22 NYCRR` / `NYCRR` citation routing is handled by `read_section.py` instead of the alias table.
- Source URLs point to NY Courts anchors, e.g. `https://www.nycourts.gov/ctapps/500rules.htm#10` and `https://www.nycourts.gov/courts/ad1/Practice&Procedures/rules.shtml#1250.2`.

New York Unified Court System rules are bundled as synthetic law `NYUCS`:

- `references/laws/NYUCS/index.json` — Rules of the Chief Judge, Rules of the Chief Administrator, and Uniform Rules of the Trial Courts downloaded from `https://www.nycourts.gov/rules`.
- `references/laws/NYUCS/sections.html` — compact section text for 22 NYCRR sections such as Part 202, Part 205, Part 208, and Part 221.
- Common aliases include `NYUCS`, `UCS Rules`, `NY Court Rules`, `Part 202`, `22 NYCRR Part 202`, and `UCS Part 202` (with part-specific aliases for the downloaded parts).
- Source URLs point to NY Courts rule pages with section anchors, e.g. `https://www.nycourts.gov/rules/part-202-uniform-civil-rules-supreme-court-and-county-court#section-171276`.
- Part 107 is omitted because the UCS page only states that sections 107.0-107.14 are available on Westlaw.

The statutory and Constitution corpus was refreshed from the NY Open Legislation API on August 6, 2026. It includes statutory text and section metadata; **notes, historical credits, and annotations are not included.** The `activeDate` field reflects each law or section's source version, not original enactment.

The NYC Administrative Code snapshot was generated May 26, 2026 and states that its text is current through Local Law 2026/094, enacted May 16, 2026, including amendments effective through May 17, 2026. The court-rule snapshots were generated June 27, 2026. These corpora do not include Westlaw-only text, annotations, historical credits, or amendment history beyond what appears on the source pages.

The `read_section.py` script resolves `references/` relative to its own file, so you can invoke it with an absolute path from any working directory.

Before the first command, locate the reader. In Claude Cowork, the Skill tool's displayed host-side base path may not be visible inside the workspace VM. Marketplace plugins are normally under `.remote-plugins`, while standalone skills are normally under `.claude/skills`; do not guess either path. Resolve it once:

```bash
SCRIPT="scripts/read_section.py"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$(find /sessions -type f -path '*/.remote-plugins/*/skills/ny-laws/scripts/read_section.py' -print -quit 2>/dev/null)"
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  SCRIPT="$(find /sessions -type f -path '*/skills/ny-laws/scripts/read_section.py' -print -quit 2>/dev/null)"
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  echo "Could not locate the installed New York Laws reader." >&2
  exit 1
fi
```

Use `python "$SCRIPT" ...` for all commands. Do not `cd` to an assumed `.claude/skills` or `.remote-plugins` path.

## Lookup script

`scripts/read_section.py` handles citation resolution, discovery, and listing. Run `python "$SCRIPT" --help` for the current complete option list.

### Read one or more sections

```bash
python "$SCRIPT" "CPLR 4518"
python "$SCRIPT" "NY Constitution A1S1"
python "$SCRIPT" "NYCAC 1-101"
python "$SCRIPT" "NYC Admin Code 3-113.1"
python "$SCRIPT" "22 NYCRR 500.10"
python "$SCRIPT" "22 NYCRR 1250.8"
python "$SCRIPT" "22 NYCRR 202.5-b"
python "$SCRIPT" "Part 202 202.5-b"
python "$SCRIPT" "ABC 100" "ABC 101" "ABC 102"
python "$SCRIPT" "VTL 100" --format json
python "$SCRIPT" "CPLR 4518" --format markdown
```

For broad `22 NYCRR` / `NYCRR` citations, `read_section.py` routes sections in Parts 500, 600, and 1250 to `NYCRR22`; other downloaded UCS rule parts route to `NYUCS`.

Plain text is the default. Every read prints a one-line banner showing citation, title, `activeDate`, repealed status, character count, and the public nysenate.gov URL — for both single and multi-citation calls.

### Slice a section by subsection

Long sections (e.g., ABC § 101 at ~158KB) are unreadable end-to-end. Use `--subsections` to keep only the top-level numbered subsections you need:

```bash
python "$SCRIPT" "ABC 101" --subsections 1,2
python "$SCRIPT" "CAN 80" --subsections 2-3
```

Subsection detection is heuristic — it looks for `N.` markers preceded by a sentence-ending period, which avoids false positives from inline numbered lists (metes-and-bounds surveys, etc.). If no markers are found, the full text is printed with a stderr warning.

### Cap output size

```bash
python "$SCRIPT" "ABC 101" --max-bytes 8000
```

Truncates each section's text at the byte limit with a clear `[... truncated N of M chars ...]` marker. Useful for huge sections when you only need the opening.

### Compare two or more sections

```bash
python "$SCRIPT" --compare "ABC 101" "CAN 80"
python "$SCRIPT" --compare "ABC 101" "CAN 80" --max-bytes 4000
```

Prints a summary table (citation, title, active date, repealed, length, URL) followed by each section's full text with banner. Combine with `--max-bytes` or per-citation `--subsections` workflows.

### Read an entire article

```bash
python "$SCRIPT" --read-article "CAN A4"   # all sections in Cannabis Law Article 4
python "$SCRIPT" --read-article "ABC A5" --format markdown
```

### Discover what's in the corpus

```bash
python "$SCRIPT" --list-laws            # every law + aliases + section counts
python "$SCRIPT" --list ABC             # all ABC sections grouped by article (repealed flagged)
python "$SCRIPT" --list NYCAC --article 3  # NYC Admin Code Title 3 grouped by title/chapter
python "$SCRIPT" --list NYUCS --article P202  # UCS Part 202 sections
python "$SCRIPT" --list ABC --article A8  # one article only
```

`--list` annotates each section with an approximate size tag (e.g. `[~25KB]`, `[~158KB ⚠]`) for sections over 20KB so you can budget reads — pair large ones with `--subsections` or `--max-bytes`.

### Citation-aware search

`--search` walks the corpus and reports hits as `LAW § — title` with surrounding snippets, so you can jump straight to a section read without mapping HTML line numbers back to anchors yourself. Pass law aliases as positional args to scope the search; omit them to search every law.

```bash
# All matches in the Cannabis Law
python "$SCRIPT" --search "twenty-one" CAN

# Cross-law search (no scope = all laws)
python "$SCRIPT" --search "tied house"

# NYC Admin Code search
python "$SCRIPT" --search "memoranda of understanding" NYCAC

# UCS court rules search
python "$SCRIPT" --search "electronic filing" NYUCS --titles-only

# Regex + case-sensitive
python "$SCRIPT" --search "\bdram shop\b" --regex GOB

# Titles only (great for "where is X licensed/defined")
python "$SCRIPT" --search "license" CAN --titles-only

# Limit snippets per section (default 2)
python "$SCRIPT" --search "minor" ABC CAN --max-per-section 1
```

For ad-hoc work you can still grep the raw files directly (`grep -in 'phrase' references/laws/CAN/sections.html`), but `--search` is the right default because its output is in section-citation coordinates, not HTML line numbers.

## Citation workflow

1. If the user gives a citation, resolve it with `python "$SCRIPT" "<prefix> <section>"`.
2. If the prefix is unknown, read the error suggestions, then run `--list-laws` (or inspect `references/aliases.json`).
3. If the section ID is unknown, run `--list <LAW>` (optionally `--article`) or `--search <keyword> <LAW> --titles-only`.
4. For topic-based discovery ("where does NY regulate X"), use `--search "<phrase>"` (optionally scoped to specific laws), then read the matching sections.
5. Before describing any section's substantive requirements—including definitions, exceptions, remedies, or enforcement—read that section from the bundled corpus. Search and listing results are for discovery, not substantive summaries.
6. Quote only the exact statutory language needed.
7. Check `repealed` and `activeDate` before treating a section as currently operative. The default plain-text output for batched reads and the markdown format both surface this; for single-citation plain-text calls, use `--format markdown` or `--format json` if currency matters.
8. State that this corpus omits notes if the user asks about historical notes, credits, amendments, annotations, or official commentary. For UCS rules, also state that Westlaw-only text is not included.
