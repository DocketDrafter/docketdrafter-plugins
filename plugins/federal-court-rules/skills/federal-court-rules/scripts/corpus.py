"""Shared first-use corpus resolver for DocketDrafter reader scripts."""

import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BUCKET_BASE = "https://public-corpora.docketdrafter.com"


def _library(corpus):
    configured = os.environ.get("DOCKETDRAFTER_DATA_DIR")
    base = Path(configured).expanduser() if configured else Path.home() / "Documents" / "DocketDrafter Library"
    return base / "corpora" / corpus


def _content_checkout(corpus):
    configured = os.environ.get("DOCKETDRAFTER_CONTENT_REPO")
    if not configured:
        return None
    references = Path(configured).expanduser() / "corpora" / corpus / "references"
    if not (references / "index.json").is_file():
        raise SystemExit(f"DOCKETDRAFTER_CONTENT_REPO is set, but the {corpus} corpus was not found at {references}")
    return references


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_target(destination, name):
    target = (destination / name).resolve()
    if target != destination and destination not in target.parents:
        raise SystemExit(f"Unsafe path in corpus archive: {name}")


def _extract(archive, destination, archive_format):
    destination = destination.resolve()
    total = 0
    if archive_format == "zip":
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                _safe_target(destination, item.filename)
                total += item.file_size
                if total > 2 * 1024 * 1024 * 1024:
                    raise SystemExit("Corpus archive expands beyond the 2 GB safety limit")
            source.extractall(destination)
        return
    if archive_format == "tar.xz":
        with tarfile.open(archive, mode="r:xz") as source:
            members = source.getmembers()
            for item in members:
                _safe_target(destination, item.name)
                if not (item.isfile() or item.isdir()):
                    raise SystemExit(f"Unsupported entry in corpus archive: {item.name}")
                total += item.size
                if total > 2 * 1024 * 1024 * 1024:
                    raise SystemExit("Corpus archive expands beyond the 2 GB safety limit")
            source.extractall(destination, members=members)
        return
    raise SystemExit(f"Unsupported corpus archive format: {archive_format}")

def _fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except Exception as exc:
        raise SystemExit(f"Could not retrieve the {url.rsplit('/', 2)[-2]} release manifest: {exc}")


def ensure_corpus(corpus):
    if checkout := _content_checkout(corpus):
        return checkout

    skill_references = Path(__file__).resolve().parents[1] / "references"
    if (skill_references / "index.json").is_file():
        return skill_references

    destination = _library(corpus)
    references = destination / "references"
    marker = destination / "installed.json"
    # Deliberately do not check latest again after a successful installation.
    if (references / "index.json").is_file() and marker.is_file():
        return references

    latest_url = f"{BUCKET_BASE}/{corpus}/latest.json"
    release = _fetch_json(latest_url)
    required = {"corpus", "version", "artifactUrl", "sha256", "compressedBytes"}
    missing = required.difference(release)
    if missing or release.get("corpus") != corpus:
        raise SystemExit(f"Invalid {corpus} release manifest; missing fields: {sorted(missing)}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Installing the latest {corpus} corpus ({release['compressedBytes'] / 1048576:.1f} MB)…", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix=f"{corpus}-", dir=destination.parent) as temp_name:
        temp = Path(temp_name)
        archive = temp / "corpus.archive"
        try:
            with urllib.request.urlopen(release["artifactUrl"], timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        except Exception as exc:
            raise SystemExit(f"Could not download the {corpus} corpus: {exc}")
        digest = _sha256(archive)
        if digest != release["sha256"]:
            raise SystemExit(f"{corpus} corpus checksum mismatch: expected {release['sha256']}, got {digest}")
        unpacked = temp / "unpacked"
        unpacked.mkdir()
        _extract(archive, unpacked, release.get("format", "zip"))
        if not (unpacked / "references" / "index.json").is_file():
            raise SystemExit(f"Downloaded {corpus} corpus is missing references/index.json")
        (unpacked / "installed.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            shutil.rmtree(destination)
        unpacked.replace(destination)
    print(f"Installed {corpus} corpus {release['version']}.", file=sys.stderr)
    return references
