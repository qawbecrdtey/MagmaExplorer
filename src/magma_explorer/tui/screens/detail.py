"""Detail screen: tabbed op-table and properties view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, TabbedContent, TabPane

from magma_explorer.client import ClientError
from magma_explorer.magma import Magma, TableParseError, parse_table
from magma_explorer.tui.widgets import OpTableView, PropsPanel


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("1", "show_tab('tab-table')", "Table"),
        Binding("2", "show_tab('tab-props')", "Properties"),
    ]

    def __init__(self, *, magma: Magma) -> None:
        super().__init__()
        self.magma = magma

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="tab-table", id="tabs"):
            with TabPane("Table", id="tab-table"):
                yield OpTableView(id="op-table", show_cursor=False, zebra_stripes=True)
            with TabPane("Properties", id="tab-props"):
                yield PropsPanel(self.magma, id="props")
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_table()

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    async def _load_table(self) -> None:
        m = self.magma
        table_text = await self.app.cache.get_table(m.canonical_hash)
        if table_text is None:
            self.app.notify("Fetching table…")
            try:
                table_text = await self.app.client.fetch_table(m.url)
            except ClientError as exc:
                self.app.notify(f"Table fetch failed: {exc}", severity="error")
                return
            await self.app.cache.set_table(m.canonical_hash, table_text)

        try:
            table = parse_table(table_text, expected_size=m.size)
        except TableParseError as exc:
            self.app.notify(f"Table parse error: {exc}", severity="error")
            return

        self.query_one("#op-table", OpTableView).populate(table)
