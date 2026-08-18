---
name: us-code
description: Use when an agent needs to look up, quote, summarize, cite, or reason from the United States Code. Provides local full-corpus access to U.S. Code title sections through compact HTML section files and a citation lookup script.
---

# U.S. Code

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill when a task requires local U.S. Code text, section lookup, statutory citation checking, or statutory analysis based on federal code sections.

After first-use installation, lookup, listing, comparison, and search operate entirely against the local corpus.

Before the first command, locate the reader once. Cowork standalone skills normally use the first path below; the fallback also supports marketplace plugins and Claude Code:

```bash
SCRIPT="/root/.claude/skills/synced/us-code/scripts/read_section.py"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="scripts/read_section.py"
fi
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$(find /root/.claude /sessions -type f -path '*/us-code/scripts/read_section.py' -print -quit 2>/dev/null)"
fi
if [ -z "$SCRIPT" ] || [ ! -f "$SCRIPT" ]; then
  echo "Could not locate the installed U.S. Code reader." >&2
  exit 1
fi
```

Use `python "$SCRIPT" ...` for all commands. Do not run additional filesystem-wide searches unless this block fails.

## Corpus

- `references/index.json` contains title metadata and corpus currency.
- `references/titles/{titleKey}/index.json` supports citation and heading lookup.
- Each title's `sections.html` contains its statutory section text.
- The first-use installer may normalize release files during extraction; the reader handles both canonical and distributed representations transparently.
- Appendix titles use keys such as `18-app`.

**Source checked August 6, 2026.** The latest OLRC bulk preliminary release available on that date was current through **Public Law 119-102, July 12, 2026**. An installed corpus does not update itself at runtime.

This corpus includes statutory section text and section metadata only. **Source credits, amendment and effective-date notes, transfer and historical notes, and other editorial material are not included.**

## Lookup script

`scripts/read_section.py` handles citation resolution, discovery, listing, comparison, and search.

### Read one or more sections

```bash
python "$SCRIPT" "42 U.S.C. § 1983"
python "$SCRIPT" "28 USC 1332" "28 USC 1331"
python "$SCRIPT" "42 USC 1983" --format markdown
python "$SCRIPT" "18 App. U.S.C. § 1"
```

Plain text is the default. Every read prints a one-line banner showing the citation, heading, corpus currency, placeholder flag, character count, an official OLRC URL, and a Cornell LII convenience URL. The links let users inspect the source online; the agent should use the bundled local text for research and retrieval. Prefer the official OLRC link when citing a source for the user, with Cornell as an optional convenience link. URLs are generated at read time and are not duplicated in the corpus indexes.

### Slice a section by subsection

Long sections (e.g., 18 U.S.C. § 1961 at ~8KB) can be sliced to the subsections you need. USC uses `(a)`, `(b)`, `(c)` as top-level markers most often, but some sections use `(1)`, `(2)`, etc.:

```bash
python "$SCRIPT" "18 USC 1962" --subsections a,b
python "$SCRIPT" "18 USC 1962" --subsections a-c
python "$SCRIPT" "42 USC 1985" --subsections 1,2
```

Subsection detection is heuristic — it looks for line-leading `(a)`/`(1)` markers in sequence. If no markers are found, the full text is printed with a stderr warning.

### Cap output size

```bash
python "$SCRIPT" "18 USC 1961" --max-bytes 4000
```

Truncates each section's text at the byte limit with a clear `[... truncated N of M chars ...]` marker. Useful for huge sections when you only need the opening.

### Compare two or more sections

```bash
python "$SCRIPT" --compare "42 USC 1983" "42 USC 1985"
python "$SCRIPT" --compare "42 USC 1983" "42 USC 1985" --max-bytes 2000
```

Prints a summary table (citation, heading, currency, placeholder, length, URL) followed by each section's full text with banner.

### Read an entire chapter

```bash
python "$SCRIPT" --read-chapter "18 96"   # all sections in Title 18, Chapter 96 (RICO)
python "$SCRIPT" --read-chapter "42 21" --max-bytes 2000
```

### Discover what's in the corpus

```bash
python "$SCRIPT" --list-titles            # every USC title with section count and positive-law status
python "$SCRIPT" --list 18                # all Title 18 sections grouped by Part/Chapter (placeholders flagged)
python "$SCRIPT" --list 18 --chapter 96   # one chapter only
python "$SCRIPT" --list 18-app            # appendix titles supported
```

`--list` annotates each section with an approximate size tag (e.g. `[~25KB]`, `[~158KB ⚠]`) for sections over 20KB so you can budget reads — pair large ones with `--subsections` or `--max-bytes`.

### Citation-aware search

`--search` walks the corpus and reports hits as `TITLE U.S.C. § — heading` with surrounding snippets, so you can jump straight to a section read without mapping HTML line numbers back to anchors yourself. Pass title numbers as positional args to scope the search; omit them to search every title.

```bash
# All matches in Title 18
python "$SCRIPT" --search "racketeering" 18

# Cross-title search (no scope = all titles)
python "$SCRIPT" --search "qualified immunity"

# Regex + case-sensitive
python "$SCRIPT" --search "\bdue process\b" --regex 42

# Headings only (great for "where is X defined")
python "$SCRIPT" --search "conspiracy" 18 --headings-only

# Limit snippets per section (default 2)
python "$SCRIPT" --search "racketeering" 18 --max-per-section 1
```

`--headings-only` matches only section names. If it returns zero matches, the script reminds you to retry without the flag to search body text.

Use `--search` rather than grepping corpus files directly. It works with both plain and release-compressed data and reports results in section-citation coordinates.

## Citation workflow

1. If the user gives a citation, resolve it with `python "$SCRIPT" "<title> USC <section>"`.
2. If the title key is unknown or you need an overview, run `--list-titles`.
3. If the section ID is unknown, run `--list <title>` (optionally `--chapter`) or `--search <keyword> <title> --headings-only`.
4. For topic-based discovery ("where does federal law regulate X"), use `--search "<phrase>"` (optionally scoped to specific titles), then read the matching sections.
5. Before describing any section's substantive requirements—including remedies, enforcement, exceptions, or definitions—read that section from the bundled corpus. A heading or search result is sufficient for discovery, but not for summarizing statutory requirements.
6. Quote only the exact statutory language needed.
7. Check `isPlaceholder` and `lawsEnactedThrough` before treating a section as currently operative. The default plain-text banner and markdown format both surface this.
8. Use appendix title keys like `18-app` (or include `App.` in the citation) when the citation includes an appendix reference.
9. State that this corpus omits notes if the user asks about historical notes, source credits, amendments, annotations, or official commentary.
