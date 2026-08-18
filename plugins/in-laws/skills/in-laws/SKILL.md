---
name: in-laws
description: Use when an agent needs to look up, quote, search, summarize, cite, or reason from the Indiana Code or Indiana Constitution.
---

# Indiana Laws

The reader scripts automatically install the latest verified corpus on first use. After installation, lookups are local and the corpus is not checked for updates in that environment.

Use this skill for Indiana statutory and constitutional research. Generated primary-source material is under `references/`; source URLs and retrieval dates are recorded in its indexes.

## Lookup

```bash
python scripts/read_section.py "IC 35-42-1-1"
python scripts/read_section.py --list-titles
python scripts/read_section.py --list-title 35 --chapter 42
python scripts/read_section.py --search "deadly force"
python scripts/read_constitution.py "Article 1, Section 9"
```

## Updating

Downloading and parsing are intentionally separate. Raw source files are retained under gitignored `.dev/data/raw/`.

```bash
python .dev/scripts/download.py --edition 2026 --force
python .dev/scripts/build.py --edition 2026
```

Use `--force` when refreshing an existing edition; without it, previously downloaded raw files remain cached. The downloader validates that title responses contain Code content and that the Constitution response is a PDF. The builder never uses the network. It uses only the PDF text layer through `pdftotext`; it does not perform OCR and stops if the text layer is unusable.

Source pages: `https://iga.in.gov/laws/2026/ic/titles/1` and the Indiana General Assembly's Constitution publication.
