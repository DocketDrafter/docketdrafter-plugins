"""Configuration helpers for the CourtListener skill."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / "Documents" / "CourtListener Library"
SETTINGS_DIR = Path.home() / ".courtlistener"
SETTINGS_FILE = SETTINGS_DIR / "settings"
LIBRARY_SETTINGS_DIR_NAME = ".courtlistener"
LIBRARY_SETTINGS_NAME = "settings"


def _load_settings(path: Path) -> dict[str, str]:
    """Read a small settings file without requiring shell syntax."""
    if not path.exists():
        return {}
    settings: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip()
    return settings


def get_data_dir() -> Path:
    """Return the configured persistent CourtListener Library directory."""
    configured = os.getenv("COURTLISTENER_DATA_DIR") or _load_settings(SETTINGS_FILE).get(
        "COURTLISTENER_DATA_DIR"
    )
    if configured:
        return Path(configured).expanduser().resolve()
    if is_cowork_sandbox():
        raise ValueError(
            "Cowork is running in a temporary sandbox. Request access to "
            "~/Documents/CourtListener Library, then pass its mounted path with --data-dir."
        )
    return DEFAULT_DATA_DIR


def library_settings_file(data_dir: Path) -> Path:
    """Return the settings file stored with a persistent library."""
    return (
        data_dir.expanduser().resolve()
        / LIBRARY_SETTINGS_DIR_NAME
        / LIBRARY_SETTINGS_NAME
    )


def get_api_key(data_dir: Path | None = None) -> str | None:
    """Return an API key from the environment or persistent settings.

    The connector supplies the key via ``COURTLISTENER_API_KEY``. The settings
    files are a migration path for users who configured the key with the older
    script-based setup, so their existing key keeps working.
    """
    if api_key := os.getenv("COURTLISTENER_API_KEY"):
        return api_key
    if data_dir is None and (configured := os.getenv("COURTLISTENER_DATA_DIR")):
        data_dir = Path(configured)
    if data_dir is not None:
        if api_key := _load_settings(library_settings_file(data_dir)).get(
            "COURTLISTENER_API_KEY"
        ):
            return api_key
    return _load_settings(SETTINGS_FILE).get("COURTLISTENER_API_KEY")


def is_cowork_sandbox(path: Path | None = None) -> bool:
    """Return whether the active home is a Claude Cowork session sandbox."""
    candidate = (path or Path.home()).expanduser().resolve()
    parts = candidate.parts
    return len(parts) >= 3 and parts[1] == "sessions"


def is_cowork_mounted_path(path: Path) -> bool:
    """Return whether a path is under Cowork's host-mounted mnt directory."""
    parts = path.expanduser().resolve().parts
    return len(parts) >= 5 and parts[1] == "sessions" and parts[3] == "mnt"


def ensure_directory(path: Path) -> Path:
    """Create a directory if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` so readers never observe a partial file.

    The server handles requests concurrently, so two in-flight requests can
    fetch the same opinion or docket and write the same path at the same time.
    A plain write lets a reader — or the loser of the race — see a truncated
    file. Writing to a temp file in the *same* directory and then renaming
    makes the swap atomic on POSIX, so a path always holds either the old
    complete contents or the new complete contents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write text to ``path``. See :func:`_replace_atomically`."""
    _replace_atomically(path, text.encode(encoding))


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Atomically write bytes to ``path``. See :func:`_replace_atomically`."""
    _replace_atomically(path, data)
