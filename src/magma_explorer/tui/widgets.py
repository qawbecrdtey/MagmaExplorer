"""Reusable Textual widgets shared across screens."""

from __future__ import annotations

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static

from magma_explorer.magma import Magma


class OpTableView(DataTable):
    """A ``DataTable`` specialized for n×n Cayley tables.

    The top header row (column indices) is auto-pinned by ``DataTable``;
    the row-label gutter (row indices) is also auto-pinned to the left,
    so both axes stay visible while the user scrolls.
    """

    def populate(self, table: list[list[int]]) -> None:
        self.clear(columns=True)
        n = len(table)
        cell_width = max(2, len(str(max(0, n - 1))) + 1)
        for j in range(n):
            self.add_column(str(j), key=f"col{j}", width=cell_width)
        for i, row in enumerate(table):
            self.add_row(*(str(v) for v in row), label=str(i))


class PropsPanel(VerticalScroll):
    """Scrollable panel showing all properties of a magma."""

    def __init__(self, magma: Magma, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.magma = magma

    def compose(self) -> ComposeResult:
        for line in _format_props(self.magma):
            yield Static(line)


def _format_props(m: Magma) -> Iterator[str]:
    def yn(b: bool) -> str:
        return "yes" if b else "no"

    yield f"[bold]canonical_hash[/bold]      {m.canonical_hash}"
    yield f"[bold]size[/bold]                 {m.size}"
    yield f"[bold]idempotent[/bold]           {yn(m.idempotent)}"
    yield f"[bold]right_cancellative[/bold]   {yn(m.right_cancellative)}"
    yield f"[bold]satisfies_255[/bold]        {yn(m.satisfies_255)}"
    if m.display_reorder is not None:
        yield f"[bold]display_reorder[/bold]      {m.display_reorder}"
    if m.submitted_at:
        yield f"[bold]submitted_at[/bold]         {m.submitted_at}"
    if m.submitted_by:
        yield f"[bold]submitted_by[/bold]         {m.submitted_by}"
    yield f"[bold]url[/bold]                  {m.url}"
    if m.comment:
        yield ""
        yield "[bold]comment:[/bold]"
        yield m.comment
