"""Top-level Textual app for Magma Explorer."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from magma_explorer import config as config_mod
from magma_explorer.cache import Cache
from magma_explorer.client import Client
from magma_explorer.tui.screens.browse import BrowseScreen


class MagmaExplorerApp(App):
    TITLE = "Magma Explorer"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("?", "help", "Help"),
    ]

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        cache_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._config_path = config_path
        self._cache_path = cache_path
        self.config: config_mod.Config | None = None
        self.cache: Cache | None = None
        self.client: Client | None = None

    async def on_mount(self) -> None:
        self.config, warnings = config_mod.load(self._config_path)
        self.cache = Cache(self._cache_path)
        await self.cache.init()
        self.client = Client()
        await self.push_screen(BrowseScreen(initial_warnings=warnings))

    async def action_quit(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        self.exit()

    def action_help(self) -> None:
        self.notify(
            "/ focus query  ·  enter run  ·  r refresh  ·  q quit",
            title="Bindings",
        )
