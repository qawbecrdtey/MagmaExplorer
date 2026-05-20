from pathlib import Path

import pytest

from magma_explorer.cache import Cache
from magma_explorer.magma import Magma


def _magma(hash_id: str, size: int = 5) -> Magma:
    return Magma(
        canonical_hash=hash_id,
        size=size,
        satisfies_255=True,
        right_cancellative=False,
        idempotent=True,
        display_reorder=None,
        comment="",
        submitted_at="2026-01-01 00:00:00",
        submitted_by="test",
        url=f"https://example.com/{hash_id}.txt",
    )


async def test_init_creates_schema(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    assert await cache.count_magmas() == 0


async def test_meta_round_trip(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    assert await cache.get_meta("etag") is None
    await cache.set_meta("etag", "v1")
    assert await cache.get_meta("etag") == "v1"
    await cache.set_meta("etag", "v2")
    assert await cache.get_meta("etag") == "v2"


async def test_session_round_trip(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    assert await cache.get_session("last_query") is None
    await cache.set_session("last_query", "size=5")
    assert await cache.get_session("last_query") == "size=5"


async def test_get_magma(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas([_magma("aaa", 5), _magma("bbb", 7)])

    a = await cache.get_magma("aaa")
    assert a is not None
    assert a.canonical_hash == "aaa"
    assert a.size == 5

    assert await cache.get_magma("nonexistent") is None


async def test_replace_and_query_magmas(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    magmas = [
        _magma("h1", size=3),
        _magma("h2", size=5),
        _magma("h3", size=5),
        _magma("h4", size=7),
    ]
    await cache.replace_magmas(magmas)
    assert await cache.count_magmas() == 4

    all_back = await cache.query_magmas()
    assert sorted(m.size for m in all_back) == [3, 5, 5, 7]

    fives = await cache.query_magmas(sizes=[5])
    assert {m.canonical_hash for m in fives} == {"h2", "h3"}

    empty = await cache.query_magmas(sizes=[])
    assert empty == []


async def test_query_magmas_sort_order(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas(
        [
            _magma("a", size=5),
            _magma("b", size=3),
            _magma("c", size=7),
        ]
    )
    asc = await cache.query_magmas(sort=[("size", "asc")])
    assert [m.size for m in asc] == [3, 5, 7]
    desc = await cache.query_magmas(sort=[("size", "desc")])
    assert [m.size for m in desc] == [7, 5, 3]


async def test_query_magmas_rejects_unsafe_sort(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    with pytest.raises(ValueError):
        await cache.query_magmas(sort=[("size; DROP TABLE magmas", "asc")])
    with pytest.raises(ValueError):
        await cache.query_magmas(sort=[("size", "ascendingly")])


async def test_replace_magmas_is_atomic(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas([_magma("a"), _magma("b")])
    await cache.replace_magmas([_magma("c")])
    rows = await cache.query_magmas()
    assert {m.canonical_hash for m in rows} == {"c"}


async def test_table_round_trip(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas([_magma("a", size=2)])
    assert await cache.get_table("a") is None
    await cache.set_table("a", "0 1\n1 0")
    assert await cache.get_table("a") == "0 1\n1 0"
    await cache.set_table("a", "updated")
    assert await cache.get_table("a") == "updated"


async def test_get_tables_bulk(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas(
        [
            _magma("aaa", 2),
            _magma("bbb", 3),
            _magma("ccc", 4),
        ]
    )
    await cache.set_table("aaa", "0 1\n1 0")
    await cache.set_table("ccc", "ccc-table")

    result = await cache.get_tables(["aaa", "bbb", "ccc", "missing"])
    assert result == {"aaa": "0 1\n1 0", "ccc": "ccc-table"}


async def test_get_tables_empty_input(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    assert await cache.get_tables([]) == {}


async def test_table_survives_manifest_replace(tmp_path: Path):
    cache = Cache(tmp_path / "cache.sqlite")
    await cache.init()
    await cache.replace_magmas([_magma("a", size=2)])
    await cache.set_table("a", "0 1\n1 0")
    # Refresh manifest; cached table for `a` should remain.
    await cache.replace_magmas([_magma("a", size=2), _magma("b", size=3)])
    assert await cache.get_table("a") == "0 1\n1 0"
