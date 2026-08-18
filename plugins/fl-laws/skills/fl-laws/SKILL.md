---
name: fl-laws
description: Use when an agent needs to look up, quote, summarize, cite, or reason from Florida Statutes, the Florida Constitution, or Florida court rules. Provides local full-corpus access through compact HTML files and citation lookup scripts.
---

# Florida Laws

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill when a task requires Florida statutory text, Florida constitutional text, section lookup, citation checking, or statutory/constitutional analysis.

The skill also includes local Florida court rules corpora built from Florida Bar PDFs. Use `scripts/read_section.py` for statutes, `scripts/read_constitution.py` for constitutional provisions, and `scripts/read_rule.py` for court rules.

## Corpus layout

All data lives under `references/`:

- `references/index.json` — master index. Top-level `laws` includes `FS` (Florida Statutes) and `FLCONST` (Florida Constitution), plus `rulesets` for court rules.
- `references/aliases.json` — flat `{prefix → lawId}` map. Covers statute aliases such as `FS`, `F.S.`, `Fla. Stat.`, `Florida Statutes`, plus constitution aliases such as `FLCONST`, `Fla. Const.`, and `Florida Constitution`.
- `references/laws/FS/law.json` — per-law metadata: `name`, `lawType`, `sourceUrl`, `generatedAt`, `format`.
- `references/laws/FS/index.json` — `{lawId, format, chapters, titles, sections}`.
  - `sections[sectionId]` has: `sectionNum`, `chapter`, `title` (catchline from official source), `citation` (`Fla. Stat. § X.Y`), `path` (relative to `laws/FS/`), `anchor` (`section-X.Y`), `history`, `note`, `sourceUrl`, `textLength`.
  - `chapters[chapterNum]` has: `chapterNumber`, `chapterName`, `titleNumber`, `titleName`, `path`, `sourceUrl`, `sectionCount`, `sectionIds[]`.
  - `titles[titleNumber]` groups chapters under their FL Title (e.g. `TITLE I — CONSTRUCTION OF STATUTES`).
- `references/laws/FS/chapters/chapter-NNNN.html` — one HTML file per FS chapter (zero-padded to 4 digits). Each section is wrapped in `<article id="section-X.Y" data-citation="FS X.Y">` with the cleaned body in a `<pre>` block. History and Note appear as `<p class="meta">` lines after the body.

The corpus is built from the official Florida Legislature chapter HTML pages at `leg.state.fl.us/Statutes/`. It includes statutory text, the official catchline title, and the bracketed history line. **Annotations, judicial decisions, attorney general opinions, and law revision committee comments are not included.**

Unlike most California codes, Florida sections **do** have official catchlines, so `entry.title` is authoritative.

The `read_section.py` script resolves `references/` relative to its own file, so you can invoke it with an absolute path from any working directory.

## Citation format

Florida Statutes citations are `chapter.section`, e.g. `1.015`, `90.803`, `462.14`. The chapter number is the integer before the dot; the section identifier is the whole `X.Y` string. The reader accepts any of:

- `1.015`
- `FS 1.015`
- `F.S. § 90.803`
- `Fla. Stat. § 90.803`
- `Florida Statutes section 462.14`

## Lookup script

`scripts/read_section.py` handles citation resolution, discovery, and listing.

### Read one or more sections

```bash
python scripts/read_section.py "1.015"
python scripts/read_section.py "Fla. Stat. § 90.803"
python scripts/read_section.py "90.803" "90.804"
python scripts/read_section.py "F.S. 768.81" --format json
python scripts/read_section.py "1.015" --format markdown
```

Plain text is the default. Every read prints a one-line banner with citation, catchline, character count, and the official leg.state.fl.us URL.

### Cap output size

```bash
python scripts/read_section.py "90.803" --max-bytes 5000
```

Truncates each section's text at the byte limit with a `[... truncated N of M chars ...]` marker. The History line still prints at the end. Many FL sections (especially in Chapters 90, 627, 768, and the regulatory titles) are very long — use `--max-bytes` or read just the chapter list first.

### Compare two or more sections

```bash
python scripts/read_section.py --compare "90.803" "90.804"
python scripts/read_section.py --compare "768.81" "768.82" --max-bytes 4000
```

Prints a summary table (citation, title, length, URL) followed by each section's full text with banner.

### Discover what's in the corpus

```bash
python scripts/read_section.py --list-laws            # FS + alias + section/chapter counts
python scripts/read_section.py --list-chapters        # every FS chapter with name
python scripts/read_section.py --list-chapter 90      # all sections in Chapter 90 (Evidence Code)
```

`--list-chapter` annotates each section with an approximate size tag (e.g. `[~25KB]`, `[~158KB !]`) for sections over 20KB so you can budget reads.

### Citation-aware search

`--search` walks the corpus and reports hits as `<citation> — title` with surrounding snippets, so you can jump straight to a section read without mapping HTML line numbers back to anchors yourself.

```bash
# All matches in Chapter 90 (Evidence Code)
python scripts/read_section.py --search "hearsay" --chapter 90

# Whole-FS search
python scripts/read_section.py --search "comparative negligence"

# Regex + case-sensitive
python scripts/read_section.py --search "\\bproximate cause\\b" --regex --case-sensitive

# Titles only (good for "where is X defined")
python scripts/read_section.py --search "insurance" --titles-only

# Limit snippets per section (default 2)
python scripts/read_section.py --search "default judgment" --max-per-section 1
```

For ad-hoc work you can still grep the raw files directly (`grep -in 'phrase' references/laws/FS/chapters/chapter-0090.html`), but `--search` is the right default because its output is in section-citation coordinates, not HTML line numbers.

## Florida Constitution corpus

Florida Constitution data lives under `references/laws/FLCONST/`:

- `references/laws/FLCONST/law.json` — metadata for the Florida Constitution corpus.
- `references/laws/FLCONST/index.json` — `{lawId, name, format, title, preamble, articles, sections}`.
  - `articles[articleRoman]` has: `articleNumber`, `articleRoman`, `articleName`, `path`, `sourceAnchor`, `sourceUrl`, `sectionCount`, `sectionIds[]`.
  - `sections[sectionId]` has: `sectionId` (`I.23`), `articleNumber`, `articleRoman`, `articleName`, `sectionNumber`, `title`, `citation` (`Fla. Const. art. I, § 23`), `path`, `anchor`, `sourceAnchor`, `sourceUrl`, `history`, `note`, `textLength`.
- `references/laws/FLCONST/articles/article-NN.html` — one HTML file per article. Each section is wrapped in `<article>` with a cleaned body in a `<pre>` block. History and Note appear as metadata lines after the body.

The corpus is built from the official Florida Senate HTML page at `https://www.flsenate.gov/laws/constitution`. Raw downloaded HTML is kept only under `.dev/data/constitution/`, which is gitignored. The committed corpus contains cleaned per-article HTML plus JSON indexes.

### Read one or more constitutional provisions

```bash
python scripts/read_constitution.py "Fla. Const. art. I, § 23"
python scripts/read_constitution.py "Article V section 3"
python scripts/read_constitution.py "X.24" --format markdown
```

The reader accepts Bluebook-style citations, plain article/section phrases, and compact `Article.Section` forms where the article may be Roman or numeric.

### Discover and search constitutional text

```bash
python scripts/read_constitution.py --list-articles
python scripts/read_constitution.py --list-article X
python scripts/read_constitution.py --search "homestead"
python scripts/read_constitution.py --search "privacy" --titles-only
python scripts/read_constitution.py --search "supreme court" --article V
```

When citing constitutional text, use the citation printed by `read_constitution.py`, such as `Fla. Const. art. I, § 23`.

## Court rules corpus

Florida court rules data lives under `references/rules/<rulesetId>/`. Current rulesets are:

- `FLRCP` — Florida Rules of Civil Procedure.
- `FLRGPJA` — Florida Rules of General Practice and Judicial Administration.
- `FLRCrimP` — Florida Rules of Criminal Procedure.
- `FLSVP` — Florida Rules of Civil Procedure for Involuntary Commitment of Sexually Violent Predators.
- `FLProbR` — Florida Probate Rules.
- `FLRTrafP` — Florida Rules of Traffic Court.
- `FLSmClR` — Florida Small Claims Rules.
- `FLRJuvP` — Florida Rules of Juvenile Procedure.
- `FLRAppP` — Florida Rules of Appellate Procedure.
- `FLFamLRP` — Florida Family Law Rules of Procedure.

Each ruleset has the same layout:

- `references/rules/<rulesetId>/ruleset.json` — ruleset metadata.
- `references/rules/<rulesetId>/index.json` — `{rulesetId, format, rules}`.
  - `rules[ruleNum]` has: `ruleNum`, `title`, `citation` (`Fla. R. Civ. P. X.XXX`), `path`, `anchor`, `sourceUrl`, `sourcePdf`, `textLength`, `ruleTextLength`, and `noteLengths`.
- `references/rules/<rulesetId>/rules/rule-X.XXX.html` — one HTML file per rule or form. Main text is in `<pre class="rule-text">`. Committee notes and court commentary are stored separately as `<section class="rule-note" data-note-type="...">`.
- `references/rule_aliases.json` — flat `{prefix → rulesetId}` map for ruleset IDs, short citations, and related variants.

The corpus is built from PDFs in `.dev/data/FL Court Rules/`, which were published by The Florida Bar and have usable embedded text layers. It includes rule text, forms, committee notes, court notes, and commentary that appear in those PDFs.

### Read one or more rules

```bash
python scripts/read_rule.py "1.500"
python scripts/read_rule.py "Fla. R. Civ. P. 1.580"
python scripts/read_rule.py "Fla. Sm. Cl. R. 7.090"
python scripts/read_rule.py "2.514"
python scripts/read_rule.py "1.500" --format markdown
python scripts/read_rule.py "1.500" --omit-notes
```

By default, rule reads include committee notes and court commentary. Use `--omit-notes` to return only the rule/form text. Raw numeric citations are resolved by chapter prefix, e.g. `2.514` resolves to the General Practice and Judicial Administration rules and `7.090` resolves to the Small Claims Rules.

### Discover and search rules

```bash
python scripts/read_rule.py --list-rules
python scripts/read_rule.py --search "default judgment"
python scripts/read_rule.py --search "writ of possession" --omit-notes
python scripts/read_rule.py --search "defaults" --titles-only
```

For procedure questions, first check the statutes if Chapter 83 or another statute controls the issue, then check the relevant court rule with `read_rule.py`. When citing rules, use the short citation printed by `read_rule.py`, such as `Fla. R. Civ. P. X.XXX`, `Fla. R. Gen. Prac. & Jud. Admin. X.XXX`, or `Fla. Sm. Cl. R. X.XXX`.

## Citation workflow

1. If the user gives a Florida Statutes citation, resolve it with `scripts/read_section.py "<citation>"`. The parser accepts raw section IDs (`1.015`), short forms (`FS 1.015`, `F.S. § 90.803`), and Bluebook forms (`Fla. Stat. § 90.803`).
2. If the user gives a Florida Constitution citation, resolve it with `scripts/read_constitution.py "<citation>"`. The parser accepts Bluebook forms (`Fla. Const. art. I, § 23`), plain forms (`Article I section 23`), and compact forms (`I.23`).
3. If the user gives a Florida Rules of Civil Procedure citation, resolve it with `scripts/read_rule.py "<citation>"`. The parser accepts raw rule IDs (`1.500`), short forms (`FLRCP 1.500`), and Bluebook-style forms (`Fla. R. Civ. P. 1.500`).
4. If the statute section ID is unknown, run `--list-chapter <chapter>` to browse one chapter, or `--list-chapters` to find the right chapter by name. If the constitutional section is unknown, run `read_constitution.py --list-articles` or `read_constitution.py --list-article <article>`. If the rule ID is unknown, run `read_rule.py --list-rules`.
5. For topic-based discovery ("where does FL regulate X"), use `--search "<phrase>"` in the relevant corpus, optionally scoped to a statute chapter with `--chapter`, a constitutional article with `--article`, or a court-rules search with `read_rule.py`. Pair with `--titles-only` first for catchline/rule-title scans.
6. Quote only the exact statutory, constitutional, or rule language needed. Cite statutes as `Fla. Stat. § X.Y`, constitutional provisions as `Fla. Const. art. X, § Y`, and civil rules as `Fla. R. Civ. P. X.XXX`.
7. State that this corpus omits annotations if the user asks about case law construing the statute/constitutional provision, AG opinions, or session-law history beyond the bundled history/note text.

## Known limitations

- **Limited primary sources.** The bundled primary sources currently cover Florida Statutes, the Florida Constitution, and the listed Florida court rules. The Florida Administrative Code is not included.
- **Court rules are limited to bundled statewide PDFs.** The rules corpus includes the Florida Bar statewide rules PDFs listed above. It does not include local administrative orders, local clerk forms, or rules chapters not listed in `rules-index.html` unless those are separately added.
- **No annotations.** Case annotations, AG opinions, and treatise commentary are not in the official Florida Legislature HTML feed. Use Westlaw/Lexis for those.
- **No effective-date metadata.** The Florida Legislature site does not surface a structured effective date per section the way California's PUBINFO does. The `history` field is the bracketed session-law chain (e.g. `s. 1, ch. 2024-147`); read the most recent chapter number to gauge currency. Sections under a `Note` block frequently have important timing or scope caveats — they are preserved in `entry.note` and printed after the body.
- **One snapshot per corpus.** Statutes are built from a single scrape of `leg.state.fl.us`; refresh by re-running `scripts/download_chapter_html.py` and then `scripts/build_from_chapter_html.py`. The constitution is built from a cached Senate HTML page; refresh by re-running `scripts/download_constitution_html.py` and then `scripts/build_constitution.py`.
