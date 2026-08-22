---
name: ma-laws
description: Use when an agent needs to look up, quote, search, summarize, cite, or reason from the Massachusetts General Laws.
---

# Massachusetts Laws

Use this skill for Massachusetts statutory research. The corpus is generated from the official Massachusetts General Court website.

On the first lookup, `read_section.py` resolves the latest Massachusetts release, downloads its corpus from DocketDrafter's public S3 bucket, verifies its SHA-256 checksum, and installs it under `~/Documents/DocketDrafter Library/corpora/ma-laws/`. Subsequent research is local and works offline. Set `DOCKETDRAFTER_DATA_DIR` to use a different library directory.

## Lookup

```bash
python scripts/read_section.py "Mass. Gen. Laws ch. 93A, § 2"
python scripts/read_section.py "M.G.L. c. 260, § 2A"
python scripts/read_section.py "Chapter 149, Section 148"
python scripts/read_section.py --search "public records" --limit 20
python scripts/read_section.py --list-chapter 93A
```

Use `--format json` or `--format markdown` for structured output, and `--max-bytes N` to limit displayed text. Lookup and search results include links to the official section pages.

Always use `scripts/read_section.py` for research. Treat the corpus as current only as of the retrieval timestamp in `references/index.json`, and consult the linked official page when source authority or very recent amendments matter.

Source: https://malegislature.gov/Laws/GeneralLaws
