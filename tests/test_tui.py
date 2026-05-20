from pathlib import Path

from textual.widgets import DataTable

from magma_explorer.cache import Cache
from magma_explorer.magma import Magma
from magma_explorer.tui.app import MagmaExplorerApp
from magma_explorer.tui.screens.browse import BrowseScreen
from magma_explorer.tui.screens.detail import DetailScreen
from magma_explorer.tui.widgets import OpTableView


def _magma(hash_id: str, size: int) -> Magma:
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


async def _make_app(tmp_path: Path) -> MagmaExplorerApp:
    return MagmaExplorerApp(
        config_path=tmp_path / "config.toml",
        cache_path=tmp_path / "cache.sqlite",
    )


async def test_app_launches_with_empty_cache(tmp_path: Path):
    app = await _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)
        assert app.cache is not None
        assert app.config is not None
        assert await app.cache.count_magmas() == 0


async def test_browse_query_filters_pre_populated_cache(tmp_path: Path):
    cache_path = tmp_path / "cache.sqlite"
    cache = Cache(cache_path)
    await cache.init()
    await cache.replace_magmas(
        [
            _magma("aaa", 3),
            _magma("bbb", 5),
            _magma("ccc", 5),
            _magma("ddd", 7),
        ]
    )

    app = MagmaExplorerApp(
        config_path=tmp_path / "config.toml",
        cache_path=cache_path,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BrowseScreen)
        await screen._run_query("size=5")
        await pilot.pause()
        table = app.query_one("#results", DataTable)
        assert table.row_count == 2


async def test_browse_invalid_query_does_not_crash(tmp_path: Path):
    app = await _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BrowseScreen)
        await screen._run_query("size=abc")  # parser rejects
        await pilot.pause()
        table = app.query_one("#results", DataTable)
        assert table.row_count == 0


async def test_detail_screen_renders_cached_table(tmp_path: Path):
    cache_path = tmp_path / "cache.sqlite"
    cache = Cache(cache_path)
    await cache.init()
    m = _magma("abc", 2)
    await cache.replace_magmas([m])
    await cache.set_table("abc", "0 1\n1 0")

    app = MagmaExplorerApp(
        config_path=tmp_path / "config.toml",
        cache_path=cache_path,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(DetailScreen(magma=m))
        await pilot.pause()
        op = app.query_one("#op-table", OpTableView)
        assert op.row_count == 2
        assert len(op.columns) == 2


async def test_predicate_autofetches_and_filters_correctly(tmp_path: Path):
    """Predicate queries should fetch any missing op-tables and then filter."""
    cache_path = tmp_path / "cache.sqlite"
    cache = Cache(cache_path)
    await cache.init()

    aaa = _magma("aaa", 2)  # all idempotent
    bbb = _magma("bbb", 2)  # partial idempotent (one non-idem)
    ccc = _magma("ccc", 2)  # zero idempotent
    await cache.replace_magmas([aaa, bbb, ccc])
    # No tables cached — must be auto-fetched.

    table_data = {
        "https://example.com/aaa.txt": "0 0\n1 1",  # t[0][0]=0, t[1][1]=1 — all idem
        "https://example.com/bbb.txt": "0 1\n1 0",  # t[0][0]=0 idem, t[1][1]=0 not
        "https://example.com/ccc.txt": "1 1\n0 0",  # t[0][0]=1, t[1][1]=0 — none idem
    }

    class FakeClient:
        async def fetch_table(self, url: str) -> str:
            return table_data[url]

        async def aclose(self) -> None:
            pass

    app = MagmaExplorerApp(
        config_path=tmp_path / "config.toml",
        cache_path=cache_path,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.client.aclose()
        app.client = FakeClient()  # type: ignore[assignment]
        screen = app.screen
        assert isinstance(screen, BrowseScreen)
        table = app.query_one("#results", DataTable)

        # exists:x!=xx → bbb, ccc (the two non-fully-idempotent)
        await screen._run_query("exists(x):x!=xx")
        await pilot.pause()
        assert table.row_count == 2
        exists_neq_hashes = {row.value for row in table.rows}

        # all:x=xx → only aaa
        await screen._run_query("all(x):x=xx")
        await pilot.pause()
        assert table.row_count == 1
        all_eq_hashes = {row.value for row in table.rows}

        # DeMorgan: notall:x=xx ≡ exists:x!=xx
        await screen._run_query("notall(x):x=xx")
        await pilot.pause()
        assert {row.value for row in table.rows} == exists_neq_hashes

        # DeMorgan: notexists:x!=xx ≡ all:x=xx
        await screen._run_query("notexists(x):x!=xx")
        await pilot.pause()
        assert {row.value for row in table.rows} == all_eq_hashes


async def test_browse_remembers_last_query(tmp_path: Path):
    cache_path = tmp_path / "cache.sqlite"
    cache = Cache(cache_path)
    await cache.init()
    await cache.set_session("last_query", "size=5")
    await cache.replace_magmas([_magma("bbb", 5), _magma("ccc", 3)])

    app = MagmaExplorerApp(
        config_path=tmp_path / "config.toml",
        cache_path=cache_path,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#results", DataTable)
        assert table.row_count == 1  # only size=5 matches
