# Technical architecture and development

## Repository responsibilities

This repository contains:

- the Claude marketplace catalog;
- lightweight statute and court-rules reader plugins; and
- the source for the separately released CourtListener MCP extension.

Version-controlled legal data and corpus builders live in
[docketdrafter-plugin-content](https://github.com/DocketDrafter/docketdrafter-plugin-content).
Keeping the data separate prevents marketplace verification from cloning the corpus history.

## Corpus distribution

Readers resolve:

```text
https://public-corpora.docketdrafter.com/<corpus>/latest.json
```

The public hostname routes through CloudFront to a private S3 bucket. A release consists of:

```text
<corpus>/<version>/corpus.tar.xz
<corpus>/<version>/manifest.json
<corpus>/latest.json
```

Versioned archives are immutable and cached for one year. `latest.json` is cached for five
minutes. Manifests identify the content-repository commit, archive size, archive URL, format, and
SHA-256 checksum.

A reader resolves `latest.json` only when its corpus is absent. It verifies the archive checksum,
extracts it safely, and installs it atomically. An installed corpus is not automatically updated.

## Local reader development

Check out the content repository and set its root globally:

```bash
export DOCKETDRAFTER_CONTENT_REPO="$HOME/code/docketdrafter-plugin-content"
```

Every corpus reader then uses
`$DOCKETDRAFTER_CONTENT_REPO/corpora/<name>/references` directly and bypasses artifact downloads.

## Validation

Validate the marketplace with a current Claude Code installation:

```bash
claude plugin validate .
```

Compile-check the shared corpus bootstrap implementations with:

```bash
python3 -m compileall -q plugins/*/skills/*/scripts/corpus.py
```

## Publishing corpora

Publishing is performed from the content repository:

```bash
# Build and upload a new immutable release
python tools/publish_corpus.py oh-laws

# Update metadata without rebuilding or uploading the archive
python tools/publish_corpus.py oh-laws --metadata-only

# Promote an existing version
python tools/publish_corpus.py oh-laws --promote 2026-08-13
```

See the content repository README for the current publishing procedure.

## CourtListener release

`.github/workflows/release-courtlistener.yml` tests and publishes `courtlistener.mcpb` when the
connector or its release tooling changes. User-visible connector changes require a version bump
in `plugins/courtlistener/mcp/manifest.json`.

[Return to the main README](../README.md)
