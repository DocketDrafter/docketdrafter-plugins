"""Lookup helpers for CourtListener's bundled court identifiers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

COURTS_FILE = Path(__file__).resolve().parents[1] / "docs" / "courtlistener-courts.tsv"


@dataclass(frozen=True, slots=True)
class Court:
    court_id: str
    jurisdiction: str
    full_name: str


def load_courts(path: Path = COURTS_FILE) -> list[Court]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            Court(row["id"], row["jurisdiction"], row["full_name"])
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def get_court(court_id: str) -> Court | None:
    normalized = court_id.strip().casefold()
    return next(
        (court for court in load_courts() if court.court_id.casefold() == normalized),
        None,
    )


def search_courts(query: str) -> list[Court]:
    terms = query.strip().casefold().split()
    if not terms:
        return []
    return [
        court
        for court in load_courts()
        if all(
            term in f"{court.court_id} {court.jurisdiction} {court.full_name}".casefold()
            for term in terms
        )
    ]


def require_court(court_id: str) -> Court:
    court = get_court(court_id)
    if court is None:
        raise ValueError(
            f'Unknown CourtListener court ID: "{court_id}". '
            "Use search_courts to find the correct identifier."
        )
    return court
