"""Magma data model and Cayley-table parsing.

Equation 677 (from the Equational Theories Project):
    x = y ◇ (x ◇ ((y ◇ x) ◇ y))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class Magma:
    """A magma entry from the eq677.icarm.cloud manifest."""

    canonical_hash: str
    size: int
    satisfies_255: bool
    right_cancellative: bool
    idempotent: bool
    display_reorder: str | None
    comment: str
    submitted_at: str
    submitted_by: str
    url: str

    @classmethod
    def from_manifest_entry(cls, entry: dict) -> Self:
        return cls(
            canonical_hash=entry["canonical_hash"],
            size=int(entry["size"]),
            satisfies_255=bool(entry["satisfies_255"]),
            right_cancellative=bool(entry["right_cancellative"]),
            idempotent=bool(entry["idempotent"]),
            display_reorder=entry.get("display_reorder"),
            # Nullable strings: a present-but-null value would otherwise flow
            # through .get() and violate the cache's NOT NULL constraint.
            comment=entry.get("comment") or "",
            submitted_at=entry.get("submitted_at") or "",
            submitted_by=entry.get("submitted_by") or "",
            url=entry["url"],
        )


class TableParseError(ValueError):
    pass


def parse_table(text: str, *, expected_size: int | None = None) -> list[list[int]]:
    """Parse a Cayley table from text.

    Accepts n lines of n non-negative integers < n, whitespace- or
    comma-separated, matching the upstream `/magma/:hash/table.txt` format.
    """
    rows: list[list[int]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            row = [int(tok) for tok in line.replace(",", " ").split()]
        except ValueError as exc:
            raise TableParseError(f"line {line_no}: non-integer token") from exc
        rows.append(row)

    if not rows:
        raise TableParseError("empty table")

    n = len(rows)
    for i, row in enumerate(rows):
        if len(row) != n:
            raise TableParseError(
                f"row {i} has {len(row)} entries; expected {n} (table must be square)"
            )
        for j, v in enumerate(row):
            if not (0 <= v < n):
                raise TableParseError(f"row {i} col {j}: value {v} not in [0, {n})")

    if expected_size is not None and n != expected_size:
        raise TableParseError(f"expected size {expected_size}, got {n}")

    return rows


def satisfies_677(table: list[list[int]]) -> bool:
    """Check whether `table` satisfies Equation 677.

    Equation: x = y ◇ (x ◇ ((y ◇ x) ◇ y))
    """
    n = len(table)
    for x in range(n):
        for y in range(n):
            yx = table[y][x]
            yxy = table[yx][y]
            inner = table[x][yxy]
            if table[y][inner] != x:
                return False
    return True
