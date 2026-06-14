# Magma Explorer

A small TUI for browsing finite magmas that satisfy **Equation 677**, sourced
from the [Equation 677 Database](https://eq677.icarm.cloud/).

Equation 677 (from the [Equational Theories Project](https://teorth.github.io/equational_theories/)):

```
∀ x y.  x = y ◇ (x ◇ ((y ◇ x) ◇ y))
```

The database holds canonical Cayley tables for magmas that satisfy this
identity. This tool reads the public manifest at
`https://eq677.icarm.cloud/manifest.json`, caches it locally, and lets you
filter and inspect individual magmas in your terminal.

## Install & run

```bash
uv sync
uv run magma-explorer
```

On first launch the local cache is empty — press `r` to fetch the manifest.

## Key bindings

| Key       | Action                                       |
| --------- | -------------------------------------------- |
| `/`       | Focus the query bar                          |
| `Enter`   | Run query (in query bar) · open detail (in list) |
| `r`       | Refresh the manifest (conditional GET, ETag-aware) |
| `?`       | Show a help notification                     |
| `q`       | Quit                                         |
| `Esc`     | Pop back from the detail view                |
| `1` / `2` | Switch between Table and Properties tabs (detail screen) |

## Query syntax

`size=` selects magmas by their size; the value is a comma-separated list of
positive integers or inclusive ranges.

```
size=5
size=1,5,11
size=5..7                # {5, 6, 7}
size=1,5..7,11,100..110  # {1, 5, 6, 7, 11, 100..110}
```

Ranges require `left < right` strictly (use a single number for equal
endpoints). Whitespace is not allowed anywhere in the query. An empty query
shows no rows.

### Quantified predicates

Beyond `size=`, you can filter by quantified equations over a magma's
operation. Variables are single ASCII letters; the binary operation is
written either by juxtaposition or with an explicit `*` (both mean ◇).

**Quantifiers bind their variables explicitly** and can be chained to
build mixed `∀∃` predicates. Each quantifier takes a parenthesized list
of one or more variables:

```
all(x):x=xx                              # every element is idempotent
exists(x):x!=x*x                         # at least one non-idempotent element
all(x,y):x*y=y*x                         # commutative (sugar for all(x):all(y):...)
notexists(p,q):p=q(qq)                   # no (p,q) satisfies p = q◇(q◇q)
all(x,y):x=y(x((yx)y))                   # Equation 677
all(x):exists(y):x=yx                    # every x has a left-identity partner
```

Available quantifiers: `all`, `exists`, `notall` (¬∀ ≡ ∃¬), `notexists`
(¬∃ ≡ ∀¬). Each variable can be bound only once across the chain
(`all(x):exists(x):...` and `all(x,x):...` are errors); any variable
appearing in the body must be bound by some quantifier in the chain
(no implicit free variables).

**Boolean combinations** of equations use `&` (AND) and `|` (OR), with
`&` binding tighter than `|`; both chain left-associatively:

```
all(x,y):x=yx&y!=(xx)x                                    # AND of two equations
notexists(x,y):(x!=yy|x!=y)&(xx!=y|((xx)x)x!=x)          # nested boolean
```

**Juxtaposition and `*` are strictly binary** — chained applications
need parens (`(ab)c` or `a(bc)`, not `abc`; `(x*y)*z`, not `x*y*z`).
Parens disambiguate: at any `(`, if the matching `)` content contains a
top-level `&`/`|`/`=`/`!=`, it groups a boolean expression; otherwise
it groups a term.

Multiple clauses combine with `;` (AND):

```
size=5;all(x):x=xx                       # idempotent size-5 magmas
size=2..3;exists(a):a!=a*a               # small magmas with at least one non-idem element
```

**Predicate queries auto-fetch any missing op-tables on demand.** A
pure `size=...` query never touches the network; as soon as one or more
quantifier clauses appear, the screen pulls down whatever tables aren't
already cached (status bar reports the progress) before evaluating.
Subsequent queries are instant once the tables are local. Failed
fetches (network error, 404) are skipped silently for that magma.

## Configuration

`~/.config/magma-explorer/config.toml` controls which columns appear in the
browse list and in what order, plus the default sort. The file is
auto-created with sensible defaults the first time you launch the app; edit
it and restart.

```toml
[[columns]]
id = "hash"           # one of: hash, size, idempotent, right_cancellative,
label = "Hash"        #         satisfies_255, submitted_at, submitted_by, comment
width = 12

[[columns]]
id = "size"
label = "Size"

# … omit a column to hide it; order in this file is display order …

[[sort]]
field = "size"        # one of: canonical_hash, size, idempotent,
order = "asc"         #         right_cancellative, satisfies_255,
                      #         submitted_at, submitted_by
[[sort]]
field = "canonical_hash"
order = "asc"
```

A malformed config produces a warning and the app falls back to defaults
without overwriting your file.

## Cache

A small SQLite database at `~/.cache/magma-explorer/cache.sqlite` stores:

- The full manifest (magma metadata, one row per magma)
- ETag and last-refresh timestamp for conditional revalidation
- Lazily-fetched Cayley tables (one row per opened magma)
- Session state (last query)

The cache survives manifest refreshes — cached op tables remain valid since
they are content-addressed by the canonical hash. Delete the file to start
fresh.

## Development

```bash
uv run pytest          # unit + TUI smoke tests
uv run ruff check .    # lint
uv run ruff format .   # format
```

## Disclaimer

At the time of release of the project (2026-06-14), the entire code base was written with Claude Code.
