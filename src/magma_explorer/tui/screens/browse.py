"""Browse screen: query bar + magma list + status bar."""

from __future__ import annotations

import asyncio
import datetime as _dt

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from magma_explorer import query as query_mod
from magma_explorer.client import ClientError
from magma_explorer.magma import Magma, TableParseError, parse_table
from magma_explorer.query import evaluate_all_clauses as _eval_all_clauses
from magma_explorer.tui.screens.detail import DetailScreen


class BrowseScreen(Screen):
    BINDINGS = [
        Binding("/", "focus_query", "Focus query"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, *, initial_warnings: list[str] | None = None) -> None:
        super().__init__()
        self._initial_warnings = initial_warnings or []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Query, e.g. size=1,5..7,11 — Enter to run", id="query")
        yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        for col in self.app.config.columns:
            table.add_column(col.label, key=col.id, width=col.width)

        last_query = await self.app.cache.get_session("last_query") or ""
        if last_query:
            self.query_one("#query", Input).value = last_query
            await self._run_query(last_query)

        await self._refresh_status()

        for w in self._initial_warnings:
            self.app.notify(w, severity="warning")

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    async def action_refresh(self) -> None:
        await self._refresh_manifest()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "query":
            return
        await self._run_query(event.value)
        self.query_one("#results", DataTable).focus()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        magma = await self.app.cache.get_magma(event.row_key.value)
        if magma is None:
            self.app.notify(f"Magma {event.row_key.value[:12]} not in cache.", severity="error")
            return
        await self.app.push_screen(DetailScreen(magma=magma))

    async def _run_query(self, query: str) -> None:
        try:
            q = query_mod.parse(query)
        except query_mod.QueryParseError as exc:
            self.app.notify(f"Invalid query: {exc}", severity="error")
            return

        await self.app.cache.set_session("last_query", query)

        table = self.query_one("#results", DataTable)
        table.clear()

        if q is None:
            return

        sort_keys = [(s.field, s.order) for s in self.app.config.sort]
        sizes = q.size.sizes if q.size is not None else None
        magmas = await self.app.cache.query_magmas(sizes=sizes, sort=sort_keys)

        if q.logic:
            magmas = await self._apply_logic_clauses(magmas, q.logic)

        for m in magmas:
            row = tuple(self._format_cell(col.id, m) for col in self.app.config.columns)
            table.add_row(*row, key=m.canonical_hash)

        await self._refresh_status()

    async def _apply_logic_clauses(
        self,
        magmas: list[Magma],
        clauses: tuple[query_mod.LogicClause, ...],
    ) -> list[Magma]:
        hashes = [m.canonical_hash for m in magmas]
        cached = await self.app.cache.get_tables(hashes)
        missing = [m for m in magmas if m.canonical_hash not in cached]

        if missing:
            await self._fetch_tables_bulk(missing)
            cached = await self.app.cache.get_tables(hashes)

        self._set_status("evaluating predicates…")
        kept: list[Magma] = []
        for m in magmas:
            text = cached.get(m.canonical_hash)
            if text is None:
                continue  # fetch failed; silently skip this candidate
            try:
                parsed = parse_table(text, expected_size=m.size)
            except TableParseError:
                continue
            if await asyncio.to_thread(_eval_all_clauses, clauses, parsed):
                kept.append(m)
        return kept

    async def _fetch_tables_bulk(self, magmas: list[Magma]) -> None:
        total = len(magmas)
        self._set_status(f"fetching {total} tables…")
        sem = asyncio.Semaphore(10)

        async def one(m: Magma) -> None:
            async with sem:
                try:
                    text = await self.app.client.fetch_table(m.url)
                    await self.app.cache.set_table(m.canonical_hash, text)
                except ClientError:
                    pass

        tasks = [asyncio.create_task(one(m)) for m in magmas]
        for done, task in enumerate(asyncio.as_completed(tasks), start=1):
            await task
            if done % 25 == 0 or done == total:
                self._set_status(f"fetching tables… {done}/{total}")

    async def _refresh_manifest(self) -> None:
        self._set_status("refreshing manifest…")
        try:
            etag = await self.app.cache.get_meta("etag")
            snap = await self.app.client.fetch_manifest(etag=etag)
        except ClientError as exc:
            self.app.notify(f"Refresh failed: {exc}", severity="error")
            await self._refresh_status()
            return

        if snap is None:
            self.app.notify("Manifest unchanged.", severity="information")
            await self._refresh_status()
            return

        await self.app.cache.replace_magmas(snap.magmas)
        if snap.etag:
            await self.app.cache.set_meta("etag", snap.etag)
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.app.cache.set_meta("last_refresh", now)

        self.app.notify(f"Refreshed {len(snap.magmas)} magmas.")
        current_query = self.query_one("#query", Input).value
        await self._run_query(current_query)
        await self._refresh_status()

    async def _refresh_status(self) -> None:
        count = await self.app.cache.count_magmas()
        if count == 0:
            self._set_status("cache empty · press r to fetch")
            return
        last = await self.app.cache.get_meta("last_refresh") or "never"
        self._set_status(f"cache: {count} magmas · last refresh: {last}")

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _format_cell(self, col_id: str, m: Magma) -> str:
        if col_id == "hash":
            col = next(c for c in self.app.config.columns if c.id == "hash")
            return m.canonical_hash[: col.width or 64]
        if col_id == "size":
            return str(m.size)
        if col_id in ("idempotent", "right_cancellative", "satisfies_255"):
            return "✓" if getattr(m, col_id) else "·"
        if col_id == "submitted_at":
            return m.submitted_at[:10] or "—"
        if col_id == "submitted_by":
            return m.submitted_by or "—"
        if col_id == "comment":
            s = m.comment.replace("\n", " ")
            return (s[:60] + "…") if len(s) > 60 else s
        return ""
