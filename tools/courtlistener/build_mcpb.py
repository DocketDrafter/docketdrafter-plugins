#!/usr/bin/env python3
"""Assemble the CourtListener .mcpb bundle.

The bundle uses MCPB's UV runtime (manifest v0.4). Runtime dependencies are
declared in ``mcp/pyproject.toml`` and installed by the host application, so no
generated dependency code or virtual environment is stored in the repository or
packed into the .mcpb.

Usage:
    python3 tools/courtlistener/build_mcpb.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "courtlistener"
MCP_DIR = PLUGIN_DIR / "mcp"
LIB_DIR = MCP_DIR / "lib"
PYPROJECT = MCP_DIR / "pyproject.toml"
UV_LOCK = MCP_DIR / "uv.lock"

EXCLUDE_DIRS = {"__pycache__", "vendor", ".venv", ".pytest_cache"}


def clean(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc"),
        dirs_exist_ok=True,
    )


def build(output_dir: Path) -> Path:
    staging = output_dir / "courtlistener"
    clean(staging)

    manifest = json.loads((MCP_DIR / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != "0.4" or manifest["server"].get("type") != "uv":
        raise SystemExit("CourtListener manifest must use MCPB manifest v0.4 and server.type=uv")
    if not PYPROJECT.is_file():
        raise SystemExit(f"Missing UV dependency declaration: {PYPROJECT}")

    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copy2(PYPROJECT, staging / "pyproject.toml")
    if UV_LOCK.is_file():
        shutil.copy2(UV_LOCK, staging / "uv.lock")

    server_dir = staging / "server"
    server_dir.mkdir(parents=True)
    shutil.copy2(MCP_DIR / "server.py", server_dir / "server.py")

    # The bundle is flat: server.py resolves the implementation and docs
    # relative to itself when mcp/lib is not present.
    copy_tree(LIB_DIR / "courtlistener_mcp", server_dir / "courtlistener_mcp")
    copy_tree(LIB_DIR / "docs", server_dir / "docs")

    license_file = PLUGIN_DIR / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, staging / "LICENSE")

    bundle_path = output_dir / "courtlistener.mcpb"
    bundle_path.unlink(missing_ok=True)
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(staging.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(staging))

    return bundle_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "dist"),
        help="Where to stage the bundle (default: dist/)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = build(output_dir)
    size_kb = bundle.stat().st_size / 1024
    print(f"Built {bundle} ({size_kb:.0f} KB, UV-managed dependencies)")
    print(
        "Validate with: npx @anthropic-ai/mcpb validate "
        f"{output_dir / 'courtlistener' / 'manifest.json'}"
    )


if __name__ == "__main__":
    main()
