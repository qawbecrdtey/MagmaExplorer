# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                              # install deps + editable package
uv run magma-explorer                # launch the TUI
uv run pytest                        # full test suite
uv run pytest tests/test_query.py    # one file
uv run pytest -k satisfies_677       # one test by name
uv run ruff check .                  # lint
uv run ruff format .                 # format
```

Python 3.11+ is required (uses stdlib `tomllib` and `typing.Self`).

## Architecture

The package is layered top-down with no upward imports:

```
tui/  ─────────►  client.py  ─────────►  magma.py
  │                cache.py   ─────────►   (data model)
  ▼                config.py
__main__.py
```

- **`magma.py`** holds the `Magma` dataclass plus `parse_table` and
  `satisfies_677`. The dataclass mirrors the manifest schema exactly, so
  cache rows, JSON deserialization, and the in-memory model stay aligned;
  changing one means updating the others.
- **`query.py`** is a hand-written parser + evaluator. Clauses are
  `;`-separated and AND-combined; each is either `size=...` or a logic
  clause. A logic clause is a chain of `QuantifierCall`s
  (`all(x,y):exists(z):...`) followed by a `BoolExpr` body — `EqAtom`
  leaves (`lhs OP rhs`) composed with `BoolAnd` and `BoolOr`. Precedence:
  `=`/`!=` tightest, then `&`, then `|`. `&` and `|` chain left-
  associatively (boolean composition), while juxtaposition and `*`
  inside a term are strictly binary (chains like `abc`, `x*y*z` are
  rejected). Variables are single ASCII letters; every free variable in
  the body must be bound by some quantifier in the chain, and no
  variable may be bound twice. Parens are dual-purpose: inside an
  equation they group terms; at the boolean level they group sub-
  expressions. The parser uses lookahead (`_TokenStream.is_bool_paren_group`)
  to decide which: if the matching `)` content contains any top-level
  `&`/`|`/`=`/`!=`, it's a `(BoolExpr)`; otherwise it's a term paren.
  The evaluator (`evaluate_clause`) recurses through the quantifier
  chain accumulating an env, then walks the `BoolExpr` with short-
  circuit AND/OR. Empty query parses to `None`, which BrowseScreen
  treats as "show nothing".
- **`config.py`** loads `~/.config/magma-explorer/config.toml`. Bad config
  produces a warning string returned alongside `Config.defaults()`;
  callers surface warnings via `App.notify`. The file is never
  auto-rewritten — user edits are preserved.
- **`cache.py`** wraps `sqlite3` with `asyncio.to_thread`. **Every async
  method opens a fresh connection** inside `to_thread`, so connections are
  never shared across threads. Writes use explicit `BEGIN`/`COMMIT` with
  `isolation_level=None` and WAL mode. The `magmas` and `magma_tables`
  tables intentionally have no foreign-key relationship: refreshing the
  manifest (`replace_magmas`) must not invalidate previously-cached op
  tables, since canonical hashes are content-addressed.
- **`client.py`** uses a single `httpx.AsyncClient` **without `base_url`**
  because the manifest host (`eq677.icarm.cloud`) and table CDN host
  (`eq677-magmas.icarm.cloud`) are different subdomains; the `url` field
  in each manifest entry is an absolute CDN URL and should be used
  verbatim for table fetches. Conditional GET (`If-None-Match`) is used
  for the manifest only.
- **`tui/`** is the Textual app. `MagmaExplorerApp` owns the long-lived
  `Cache`, `Client`, and `Config`; screens read those via `self.app.*`.
  Manifest refresh is **manual only** (`r` key); there is no background
  polling. Last query is persisted in the cache's `session` table so
  the next launch pre-fills the query bar. **Predicate clauses
  auto-fetch missing op-tables** via `BrowseScreen._fetch_tables_bulk`
  (`asyncio.Semaphore(10)` capping concurrency, progress in the status
  bar). Pure `size=...` queries never touch the network. Failed fetches
  are silently skipped for that single magma.

## Key invariants

- **Equation 677**: `x = y ◇ (x ◇ ((y ◇ x) ◇ y))`. The form is hardcoded in
  `satisfies_677`; if upstream renumbers, both code and README need updates.
- **DataTable axes**: `OpTableView` uses the row-label gutter for the row
  index and `add_column` for the column header. Both are auto-pinned by
  Textual — do not set `fixed_columns`/`fixed_rows`.
- **Sort SQL**: `Cache._query_magmas_sync` builds `ORDER BY` from raw
  strings, so the field/order whitelists (`_SORTABLE_FIELDS`,
  `_SORT_ORDERS`) are load-bearing for SQL safety. Keep them in sync with
  `config.VALID_SORT_FIELDS`/`VALID_ORDERS`.
- **`asyncio_mode = "auto"`** in pyproject means every `async def test_*`
  is treated as an async test — no `@pytest.mark.asyncio` needed.

## Testing the TUI

`tests/test_tui.py` uses Textual's `app.run_test()` pilot. The pattern is:
populate the cache directly, launch the app pointed at temp paths
(`config_path` and `cache_path`), then drive it either with `pilot.press`
or by calling private screen methods (e.g. `screen._run_query`). HTTP
fetches in `client.py` are tested with `httpx.MockTransport` — no live
network is hit.
