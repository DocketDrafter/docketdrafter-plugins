---
name: oh-laws
description: Use when an agent needs to look up, quote, search, summarize, cite, or reason from the Ohio Revised Code or Constitution of the State of Ohio.
---

# Ohio Laws

Use this skill for Ohio statutory and constitutional research. The corpus is generated from the official Ohio Laws website maintained by the Ohio Legislative Service Commission.

On the first lookup, `read_section.py` resolves the latest Ohio release, downloads its corpus from DocketDrafter's public S3 bucket, verifies its SHA-256 checksum, and installs it under `~/Documents/DocketDrafter Library/corpora/oh-laws/`. The reader never checks for updates after installation; subsequent research is local and works offline. Set `DOCKETDRAFTER_DATA_DIR` to use a different library directory.

## Lookup

```bash
python scripts/read_section.py "ORC 2903.01"
python scripts/read_section.py "Ohio Rev. Code § 149.43"
python scripts/read_section.py "Ohio Const. art. I, § 1"
python scripts/read_section.py --search "public record"
```

Use `--format json` or `--format markdown` for structured output, and `--max-bytes N` to limit displayed text. Results include links to the official section pages. Revised Code metadata also retains effective dates, latest-legislation descriptions, and authenticated PDF URLs when supplied by Ohio.

## Corpus installation and updates

Always use `scripts/read_section.py` for lookups and searches. It installs the latest corpus automatically if needed; do not download or extract the artifact manually.

Repository maintainers refresh the corpus with the builder in the content repository and publish a new immutable versioned artifact. Existing installations remain stable; fresh Cowork sessions receive the latest release.

Sources:

- https://codes.ohio.gov/ohio-revised-code
- https://codes.ohio.gov/ohio-constitution

The Legislative Service Commission updates the Revised Code on an ongoing basis. Treat the corpus as current only as of the retrieval timestamp in `references/index.json` and use the linked official publication when source authority or very recent amendments matter.
