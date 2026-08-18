"""Shared data models used by source adapters and scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SavedSource:
    """Represents one fetched and saved primary source."""

    source_family: str
    path: Path
    source_url: str
    description: str
    status: str = "downloaded"
