"""SQLite cache for the manifest, magmas, op tables, and session state.

A fresh ``sqlite3.Connection`` is opened inside every ``asyncio.to_thread``
call so we never share a connection across threads. WAL mode plus
explicit transactions keep refreshes atomic.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from platformdirs import user_cache_dir

from magma_explorer.magma import Magma

APP_NAME = "magma-explorer"

# Whitelist for the safe sort builder. The same names appear in
# :mod:`magma_explorer.config` as ``VALID_SORT_FIELDS``; they're duplicated
# here to keep the cache self-contained.
_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "canonical_hash",
        "size",
        "idempotent",
        "right_cancellative",
        "satisfies_255",
        "submitted_at",
        "submitted_by",
    }
)
_SORT_ORDERS: frozenset[str] = frozenset({"asc", "desc"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS magmas (
    canonical_hash      TEXT PRIMARY KEY,
    size                INTEGER NOT NULL,
    satisfies_255       INTEGER NOT NULL,
    right_cancellative  INTEGER NOT NULL,
    idempotent          INTEGER NOT NULL,
    display_reorder     TEXT,
    comment             TEXT NOT NULL DEFAULT '',
    submitted_at        TEXT NOT NULL DEFAULT '',
    submitted_by        TEXT NOT NULL DEFAULT '',
    url                 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS magmas_size_idx ON magmas(size);

CREATE TABLE IF NOT EXISTS magma_tables (
    canonical_hash  TEXT PRIMARY KEY,
    table_text      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_cache_path() -> Path:
    return Path(user_cache_dir(APP_NAME)) / "cache.sqlite"


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


class Cache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_cache_path()

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with _connect(self.path) as conn:
            conn.executescript(SCHEMA)

    # --- manifest meta -------------------------------------------------

    async def get_meta(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_kv_sync, "manifest_meta", key)

    async def set_meta(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_kv_sync, "manifest_meta", key, value)

    # --- session -------------------------------------------------------

    async def get_session(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_kv_sync, "session", key)

    async def set_session(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_kv_sync, "session", key, value)

    # --- shared kv -----------------------------------------------------

    def _get_kv_sync(self, table: str, key: str) -> str | None:
        with _connect(self.path) as conn:
            row = conn.execute(f"SELECT value FROM {table} WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def _set_kv_sync(self, table: str, key: str, value: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                f"INSERT INTO {table} (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # --- magmas --------------------------------------------------------

    async def replace_magmas(self, magmas: Iterable[Magma]) -> None:
        await asyncio.to_thread(self._replace_magmas_sync, list(magmas))

    def _replace_magmas_sync(self, magmas: list[Magma]) -> None:
        with _connect(self.path) as conn:
            try:
                conn.execute("BEGIN")
                conn.execute("DELETE FROM magmas")
                conn.executemany(
                    "INSERT INTO magmas (canonical_hash, size, satisfies_255, "
                    "right_cancellative, idempotent, display_reorder, comment, "
                    "submitted_at, submitted_by, url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            m.canonical_hash,
                            m.size,
                            int(m.satisfies_255),
                            int(m.right_cancellative),
                            int(m.idempotent),
                            m.display_reorder,
                            m.comment,
                            m.submitted_at,
                            m.submitted_by,
                            m.url,
                        )
                        for m in magmas
                    ],
                )
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise

    async def count_magmas(self) -> int:
        return await asyncio.to_thread(self._count_magmas_sync)

    def _count_magmas_sync(self) -> int:
        with _connect(self.path) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM magmas").fetchone()
            return int(row["n"])

    async def get_magma(self, canonical_hash: str) -> Magma | None:
        return await asyncio.to_thread(self._get_magma_sync, canonical_hash)

    def _get_magma_sync(self, canonical_hash: str) -> Magma | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM magmas WHERE canonical_hash = ?", (canonical_hash,)
            ).fetchone()
            return _row_to_magma(row) if row else None

    async def query_magmas(
        self,
        sizes: Iterable[int] | None = None,
        sort: Iterable[tuple[str, str]] = (("size", "asc"), ("canonical_hash", "asc")),
    ) -> list[Magma]:
        sort_list = list(sort)
        sizes_list = None if sizes is None else list(sizes)
        return await asyncio.to_thread(self._query_magmas_sync, sizes_list, sort_list)

    def _query_magmas_sync(
        self,
        sizes: list[int] | None,
        sort: list[tuple[str, str]],
    ) -> list[Magma]:
        params: list[object] = []
        where = ""
        if sizes is not None:
            if not sizes:
                return []
            placeholders = ",".join("?" * len(sizes))
            where = f"WHERE size IN ({placeholders})"
            params.extend(sizes)

        order_parts: list[str] = []
        for field_name, order in sort:
            if field_name not in _SORTABLE_FIELDS or order not in _SORT_ORDERS:
                raise ValueError(f"unsafe sort key: ({field_name!r}, {order!r})")
            order_parts.append(f"{field_name} {order.upper()}")
        order_by = f"ORDER BY {', '.join(order_parts)}" if order_parts else ""

        sql = f"SELECT * FROM magmas {where} {order_by}".strip()

        with _connect(self.path) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_magma(r) for r in rows]

    # --- op tables -----------------------------------------------------

    async def get_table(self, canonical_hash: str) -> str | None:
        return await asyncio.to_thread(self._get_table_sync, canonical_hash)

    def _get_table_sync(self, canonical_hash: str) -> str | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT table_text FROM magma_tables WHERE canonical_hash = ?",
                (canonical_hash,),
            ).fetchone()
            return row["table_text"] if row else None

    async def get_tables(self, hashes: Iterable[str]) -> dict[str, str]:
        """Return ``{hash: table_text}`` for the cached subset of ``hashes``.

        Hashes without a cached table are simply absent from the dict.
        """
        return await asyncio.to_thread(self._get_tables_sync, list(hashes))

    def _get_tables_sync(self, hashes: list[str]) -> dict[str, str]:
        if not hashes:
            return {}
        with _connect(self.path) as conn:
            # Chunk to keep SQLite below its host variable limit (defaults to
            # 999 in older builds). Modest chunk size is fine for ~thousands.
            out: dict[str, str] = {}
            chunk_size = 500
            for i in range(0, len(hashes), chunk_size):
                chunk = hashes[i : i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT canonical_hash, table_text FROM magma_tables "
                    f"WHERE canonical_hash IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    out[row["canonical_hash"]] = row["table_text"]
            return out

    async def set_table(self, canonical_hash: str, table_text: str) -> None:
        await asyncio.to_thread(self._set_table_sync, canonical_hash, table_text)

    def _set_table_sync(self, canonical_hash: str, table_text: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO magma_tables (canonical_hash, table_text) VALUES (?, ?) "
                "ON CONFLICT(canonical_hash) DO UPDATE SET table_text=excluded.table_text",
                (canonical_hash, table_text),
            )


def _row_to_magma(row: sqlite3.Row) -> Magma:
    return Magma(
        canonical_hash=row["canonical_hash"],
        size=int(row["size"]),
        satisfies_255=bool(row["satisfies_255"]),
        right_cancellative=bool(row["right_cancellative"]),
        idempotent=bool(row["idempotent"]),
        display_reorder=row["display_reorder"],
        comment=row["comment"],
        submitted_at=row["submitted_at"],
        submitted_by=row["submitted_by"],
        url=row["url"],
    )
